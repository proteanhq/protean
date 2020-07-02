# Standard Library Imports
import logging
import logging.config

from collections.abc import Iterable

# Protean
from celery import Celery, Task
from kombu import Queue
from protean.core.broker.base import BaseBroker
from protean.core.domain_event import BaseDomainEvent
from protean.domain import DomainObjects
from protean.utils import fully_qualified_name
from protean.utils.inflection import underscore

logger = logging.getLogger("protean.impl.broker.celery")


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
            "run": attrs["notify"],  # `notify` is the method to run on event
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
        """Registers Domain Events and Commands with Subscribers/Command Handlers

        Arguments:
            initiator_cls {list} -- One or more Domain Events or Commands
            consumer_cls {Subscriber/CommandHandler} -- The consumer class connected to the Domain Event or Command
        """
        if not isinstance(initiator_cls, Iterable):
            initiator_cls = [initiator_cls]

        decorated_cls_instance = self.construct_and_register_celery_task(consumer_cls)

        for initiator in initiator_cls:
            if initiator.element_type == DomainObjects.DOMAIN_EVENT:
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

    def send_message(self, initiator_obj):
        if isinstance(initiator_obj, BaseDomainEvent):
            for subscriber in self._subscribers[
                fully_qualified_name(initiator_obj.__class__)
            ]:
                if self.conn_info["IS_ASYNC"]:
                    subscriber.apply_async(
                        [initiator_obj.to_dict()], queue=subscriber.name
                    )
                else:
                    subscriber.apply([initiator_obj.to_dict()])
        else:
            raise NotImplementedError
