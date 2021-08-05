import logging
import logging.config

from collections.abc import Iterable
from typing import Dict

from celery import Celery, Task
from kombu import Queue

from protean.infra.eventing import MessageType
from protean.port.broker import BaseBroker
from protean.utils import (
    DomainObjects,
    fetch_element_cls_from_registry,
    fully_qualified_name,
)
from protean.utils.inflection import camelize, underscore

logger = logging.getLogger("protean.adapters.celery")


class ProteanTask(Task):
    """The default base class for all Task classes constructed from Subscribers/Command Handlers.
    """

    pass


class CeleryBroker(BaseBroker):
    def __init__(self, name, domain, conn_info):
        super().__init__(name, domain, conn_info)
        self.celery_app = Celery(broker=conn_info["URI"], backend=conn_info["URI"],)

        self.celery_app.conf.update(enable_utc=True)

        # We construct queues dynamically when subscribers register
        self.queues = []

    def construct_and_register_celery_task(self, consumer_cls):
        """Constructs a Celery-compliant Task class and also registers
        Task with Celery App

        Arguments:
            consumer_cls {BaseSubscriber} -- The Subscriber or Command Handler class
                                             to be converted into a Celery Task

        Returns:
            ProteanTask -- Decorated and Registered Celery Task class
        """
        attrs = consumer_cls.__dict__
        custom_attrs = {
            "run": attrs["__call__"],  # `notify` is the method to run on event
            "name": underscore(
                fully_qualified_name(consumer_cls)
            ),  # `name` will be the same as the task's queue
        }
        attrs = {**attrs, **custom_attrs}

        # Construct `decorated_cls` dynamically from `ProteanTask`.
        #   `ProteanTask` acts as the base class for all celery tasks.
        decorated_cls = type(consumer_cls.__name__ + "Task", (ProteanTask,), {**attrs})

        # Register Task class with Celery app
        decorated_cls_instance = self.celery_app.register_task(decorated_cls())

        # Add to Queue so that workers pick it up automatically
        self.queues.append(Queue(decorated_cls.name))

        return decorated_cls_instance

    def register(self, initiator_cls, consumer_cls):
        """Registers Events and Commands with Subscribers/Command Handlers

        Arguments:
            initiator_cls {list} -- One or more Events or Commands
            consumer_cls {Subscriber/CommandHandler} -- The consumer class connected to the Event or Command
        """
        if not isinstance(initiator_cls, Iterable):
            initiator_cls = [initiator_cls]

        decorated_cls_instance = self.construct_and_register_celery_task(consumer_cls)

        for initiator in initiator_cls:
            if initiator.element_type == DomainObjects.EVENT:
                self._subscribers[fully_qualified_name(initiator)].add(
                    decorated_cls_instance
                )
                logger.debug(
                    f"Registered Subscriber {decorated_cls_instance.__class__.__name__} with queue "
                    "{self.celery_app.tasks} as Celery Task"
                )
            else:
                self._command_handlers[
                    fully_qualified_name(initiator)
                ] = decorated_cls_instance

    def publish(self, message: Dict):
        if message["type"] == MessageType.EVENT.value:
            event_cls = fetch_element_cls_from_registry(
                camelize(message["name"]), (DomainObjects.EVENT,)
            )
            for subscriber in self._subscribers[fully_qualified_name(event_cls)]:
                if self.conn_info["IS_ASYNC"]:
                    subscriber.apply_async([message], queue=subscriber.name)
                else:
                    subscriber.apply([message])
        else:
            raise NotImplementedError
