from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import logging
import sys

from typing import Dict, List

from protean import UnitOfWork
from protean.core.subscriber import BaseSubscriber
from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.globals import current_domain
from protean.infra.eventing import EventLog, Message
from protean.infra.job import Job, JobTypes
from protean.utils import (
    DomainObjects,
    EventExecution,
    EventStrategy,
    fetch_element_cls_from_registry,
    fully_qualified_name,
)
from protean.utils.importlib import import_from_full_path

logging.basicConfig(
    level=logging.INFO,  # FIXME Pick up log level from config
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

        self.loop = asyncio.new_event_loop()
        # FIXME Pick max workers from config
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=3,
            # Activate domain context before processing
            initializer=self.domain.domain_context().push,
        )

        self.SHUTTING_DOWN = False

    @classmethod
    def from_domain_file(cls, domain: str, domain_file: str, **kwargs) -> Server:
        domain = import_from_full_path(domain=domain, path=domain_file)
        return cls(domain=domain, **kwargs)

    def subscribers_for(self, message: Dict) -> List[BaseSubscriber]:
        object = self.domain.from_message(message)
        return self.broker._subscribers[fully_qualified_name(object.__class__)]

    def push_messages(self) -> None:
        """Pick up published events and push to all register brokers"""
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

    def _handled(self, future, domain, job_id):
        # FIXME Handle case when future is not done
        if future.done() and not future.exception():
            with domain.domain_context():
                job = domain.repository_for(Job).get(job_id)
                job.mark_completed()

                domain.repository_for(Job).add(job)
                logger.info(f"Job {job_id} successfully completed")
        elif future.exception():
            with domain.domain_context():
                job = domain.repository_for(Job).get(job_id)
                job.mark_errored()

                domain.repository_for(Job).add(job)
                logger.info(
                    f"Error while processing job {job_id} - {future.exception()}"
                )

    def _submit_job(self, subscriber_object, job):
        # Execute Subscriber logic and handle callback synchronously
        if current_domain.config["EVENT_EXECUTION"] == EventExecution.INLINE.value:
            try:
                subscriber_object(job.payload["payload"]["payload"])
                fut = self.loop.create_future()
                fut.set_result(None)
            except Exception as exc:
                fut = self.loop.create_future()
                fut.set_exception(exc)
            finally:
                self._handled(fut, current_domain, job.job_id)
        elif current_domain.config["EVENT_EXECUTION"] == EventExecution.THREADED.value:
            # Execute Subscriber logic in a thread
            future = self.executor.submit(
                subscriber_object.__call__, job.payload["payload"]["payload"]
            )
            future.add_done_callback(
                functools.partial(
                    self._handled,
                    domain=current_domain._get_current_object(),
                    job_id=job.job_id,
                )
            )
        else:
            raise ConfigurationError(
                {
                    "domain": [
                        f"Unknown Event Execution config - should be among {[e.value for e in EventExecution]}"
                    ]
                }
            )

    def poll_for_jobs(self):
        """Poll for new jobs and execute them in threads"""
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

                logger.info(f"Submitting job {job.job_id}")
                self._submit_job(subscriber_object, job)

            # FIXME Add other job types
            # elif ... :

            # Fetch next job record to process
            job = job_repo.get_next_to_process()

        # Trampoline: self-schedule again if not shutting down
        if not self.SHUTTING_DOWN:
            self.loop.call_later(0.5, self.poll_for_jobs)

    def poll_for_messages(self):
        """This works with `add_done_callback`"""
        message = self.broker.get_next()

        # FIXME Gather maximum `max_workers` messages and wait for the next cycle
        while message:

            # Reconstruct message back to Event
            subscribers = self.subscribers_for(message)

            for subscriber in subscribers:
                if (
                    current_domain.config["EVENT_STRATEGY"]
                    == EventStrategy.DB_SUPPORTED_WITH_JOBS.value
                ):
                    with UnitOfWork():
                        # Collect registered Subscribers from Domain
                        # FIXME Execute in threads
                        job = Job(
                            type=JobTypes.SUBSCRIPTION.value,
                            payload={
                                "subscription_cls": subscriber.__name__,
                                "payload": message,
                            },
                        )
                        current_domain.repository_for(Job).add(job)
                else:
                    try:
                        subscriber()(message["payload"])
                    except Exception:
                        # FIXME Mark EventLog as Errored
                        pass

            # Fetch next message to process
            message = self.broker.get_next()

        # Trampoline: self-schedule again if not shutting down
        if not self.SHUTTING_DOWN:
            self.loop.call_later(0.5, self.poll_for_messages)

    def run(self):
        with self.domain.domain_context():
            try:
                logger.debug("Starting server...")

                self.loop.call_soon(self.push_messages)
                self.loop.call_soon(self.poll_for_messages)
                self.loop.call_soon(self.poll_for_jobs)

                if self.test_mode:
                    self.loop.call_soon(self.stop)

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
                logger.debug("Shutting down...")

                # Signal executor to finish pending futures and free resources
                self.executor.shutdown(wait=True)

                self.loop.stop()
                self.loop.close()

    def stop(self):
        self.SHUTTING_DOWN = True

        # Signal executor to finish pending futures and free resources
        self.executor.shutdown(wait=True)

        self.loop.stop()
        self.loop.close()
