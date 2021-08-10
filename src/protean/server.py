from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
import sys

from typing import Dict, List

from protean.core.subscriber import BaseSubscriber
from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.globals import current_domain
from protean.infra.eventing import EventLog, Message
from protean.infra.job import Job, JobTypes
from protean.utils import (
    DomainObjects,
    EventExecution,
    fetch_element_cls_from_registry,
    fully_qualified_name,
)
from protean.utils.importlib import import_from_full_path

logging.basicConfig(
    level=logging.DEBUG,  # FIXME Pick up log level from config
    format="%(threadName)10s %(name)18s: %(message)s",
    stream=sys.stderr,
)

logger = logging.getLogger("Server")


class Server:
    def __init__(
        self, domain: Domain, broker: str = "default", test_mode: str = False
    ) -> None:
        self.domain = domain
        self.broker = self.domain.brokers[broker]
        self.test_mode = test_mode

        self.loop = asyncio.get_event_loop()
        # FIXME Pick max workers from config
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

        self.SHUTTING_DOWN = False

    @classmethod
    def from_domain_file(cls, domain: str, domain_file: str, **kwargs) -> Server:
        domain = import_from_full_path(domain=domain, path=domain_file)
        return cls(domain=domain, **kwargs)

    def subscribers_for(self, message: Dict) -> List[BaseSubscriber]:
        object = self.domain.from_message(message)
        return self.broker._subscribers[fully_qualified_name(object.__class__)]

    async def push_messages(self) -> None:
        """Pick up published events and push to all register brokers"""
        logger.debug("Polling DB for new events to publish...")

        event_log_repo = current_domain.repository_for(EventLog)

        # Check if there are new messages to publish
        event_log = event_log_repo.get_next_to_publish()

        while event_log:
            message = Message.from_event_log(event_log)

            # FIXME Move this to separate threads?
            for _, broker in current_domain.brokers.items():
                broker.publish(message)

            # Mark event as picked up
            event_log.mark_published()
            current_domain.repository_for(EventLog).add(event_log)

            # Fetch next record to process
            event_log = event_log_repo.get_next_to_publish()

        # Trampoline: self-schedule again if not shutting down
        if not self.SHUTTING_DOWN:
            self.loop.call_later(0.5, self.push_messages)

    def handled(self, future, domain, job_id):
        exception = future.exception()
        logger.info(f"---> Future: {future}")
        if future.done() and not future.exception():
            logger.info(f"---> Job {job_id} completed successfully")

            with domain.domain_context():
                job = domain.repository_for(Job).get(job_id)
                job.mark_completed()
                domain.repository_for(Job).add(job)
                logger.info(f"---> Updated {job_id} status to COMPLETED")
        elif future.exception():
            logger.info(f"---> Job {job_id} errored - {type(exception)}")
            with domain.domain_context():
                job = domain.repository_for(Job).get(job_id)
                job.mark_errored()
                logger.info(f"---> Job: {job.to_dict()}")
                domain.repository_for(Job).add(job)
                logger.info(f"---> Updated {job_id} status to ERRORED")

    def submit_job(self, subscriber_object, job):
        # Execute Subscriber logic and handle callback synchronously
        logger.debug(f"---> {current_domain.config['EVENT_EXECUTION']}")
        if current_domain.config["EVENT_EXECUTION"] == EventExecution.INLINE.value:
            try:
                subscriber_object(job.payload["payload"]["payload"])
                fut = self.loop.create_future()
                fut.set_result(None)
            except Exception as exc:
                fut = self.loop.create_future()
                fut.set_exception(exc)
            finally:
                self.handled(fut, current_domain, job.job_id)
        elif current_domain.config["EVENT_EXECUTION"] == EventExecution.THREADED.value:
            # Execute Subscriber logic in a thread
            future = self.executor.submit(
                subscriber_object.__call__, job.payload["payload"]["payload"]
            )
            future.add_done_callback(
                functools.partial(
                    self.handled,
                    domain=current_domain._get_current_object(),
                    job_id=job.job_id,
                )
            )
        else:
            raise ConfigurationError(
                {
                    "domain": [
                        "Unknown Event Execution config - should be among {[e.value for e in EventExecution]}"
                    ]
                }
            )

    async def poll_for_jobs(self):
        """Poll for new jobs and execute them in threads"""
        logger.debug("Polling jobs...")

        job_repo = current_domain.repository_for(Job)
        # Check if there are new jobs to process
        job = job_repo.get_next_to_process()

        while job:
            # Mark job as in progress
            job.mark_in_progress()
            current_domain.repository_for(Job).add(job)

            if job.type == JobTypes.SUBSCRIPTION.value:
                subscriber_cls = fetch_element_cls_from_registry(
                    job.payload["subscription_cls"], (DomainObjects.SUBSCRIBER,)
                )
                subscriber_object = subscriber_cls()

                logger.info(f"---> Submitting job {job.job_id}")
                self.submit_job(subscriber_object, job)

            # FIXME Add other job types
            # elif ... :

            # Fetch next job record to process
            job = job_repo.get_next_to_process()

        # Trampoline: self-schedule again if not shutting down
        if not self.SHUTTING_DOWN:
            self.loop.call_later(0.5, self.poll_for_jobs)

    async def poll_for_messages(self):
        """This works with `add_done_callback`"""
        logger.debug("Polling broker for new messages...")

        message = self.broker.get_next()

        # FIXME Gather maximum `max_workers` messages and wait for the next cycle
        while message:

            # Reconstruct message back to Event
            subscribers = self.subscribers_for(message)

            if subscribers:
                with UnitOfWork():
                    # Collect registered Subscribers from Domain
                    # FIXME Execute in threads
                    for subscriber in subscribers:
                        job = Job(
                            type=JobTypes.SUBSCRIPTION.value,
                            payload={
                                "subscription_cls": subscriber.__name__,
                                "payload": message,
                            },
                        )
                        current_domain.repository_for(Job).add(job)

            # Fetch next message to process
            message = self.broker.get_next()

        # Trampoline: self-schedule again if not shutting down
        if not self.SHUTTING_DOWN:
            self.loop.call_later(0.5, self.poll_for_messages)

    def run(self):
        try:
            self.loop.call_soon(self.push_messages)
            self.loop.call_soon(self.poll_for_messages)
            self.loop.call_soon(self.poll_for_jobs)

            if self.test_mode:
                self.loop.call_soon(self.loop.stop)

            self.loop.run_forever()
        except KeyboardInterrupt:
            # Complete running tasks and cancel safely
            logger.debug("Caught Keyboard interrupt. Cancelling tasks...")
            self.SHUTTING_DOWN = True

            def shutdown_exception_handler(loop, context):
                if "exception" not in context or not isinstance(
                    context["exception"], asyncio.CancelledError
                ):
                    loop.default_exception_handler(context)

            self.loop.set_exception_handler(shutdown_exception_handler)

            ##################
            # CANCEL Elegantly
            ##################
            # Handle shutdown gracefully by waiting for all tasks to be cancelled
            # tasks = asyncio.gather(*asyncio.all_tasks(loop=loop), loop=loop, return_exceptions=True)
            # tasks.add_done_callback(lambda t: loop.stop())
            # tasks.cancel()

            # # Keep the event loop running until it is either destroyed or all
            # # tasks have really terminated
            # while not tasks.done() and not loop.is_closed():
            #     loop.run_forever()

            #####################
            # WAIT FOR COMPLETION
            #####################
            pending = asyncio.all_tasks(loop=self.loop)
            self.loop.run_until_complete(asyncio.gather(*pending))
        finally:
            logger.debug("Closing connection...")
            self.loop.close()

    def stop(self):
        self.SHUTTING_DOWN = True
        self.loop.stop()
