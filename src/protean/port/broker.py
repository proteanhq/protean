from __future__ import annotations

import logging
import logging.config

from abc import abstractmethod
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Dict, Type, Union

from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.subscriber import BaseSubscriber
from protean.utils import DomainObjects, fully_qualified_name

logger = logging.getLogger("protean.port.broker")


class _BrokerMetaclass(type):
    """
    This base metaclass processes the class declaration and constructs a meta object that can
    be used to introspect the Broker class later. Specifically, it sets up a `meta_` attribute on
    the Broker to an instance of Meta, either the default of one that is defined in the
    Broker class.

    `meta_` is setup with these attributes:
        * `aggregate`: The aggregate associated with the repository
    """

    def __new__(
        mcs: Type[type], name: str, bases: tuple, attrs: dict, **kwargs: Any
    ) -> _BrokerMetaclass:
        """Initialize Broker MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of Broker
        # (excluding Broker class itself).
        parents = [b for b in bases if isinstance(b, _BrokerMetaclass)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Remove `abstract` in base classes if defined
        for base in bases:
            if hasattr(base, "Meta") and hasattr(base.Meta, "abstract"):
                delattr(base.Meta, "abstract")

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop("Meta", None)
        meta = attr_meta or getattr(new_class, "Meta", None)
        setattr(new_class, "meta_", BrokerMeta(name, meta))

        return new_class


class BrokerMeta:
    """ Metadata info for the Broker.

    Options:
    - ``aggregate_cls``: The aggregate associated with the repository
    """

    def __init__(
        self, entity_name: str, meta: Any
    ):  # FIXME What is the type of `meta`?
        self.aggregate_cls = getattr(meta, "aggregate_cls", None)


class BaseBroker(metaclass=_BrokerMetaclass):
    """This class outlines the base broker functions,
    to be satisfied by all implementing brokers.

    It is also a marker interface for registering broker
    classes with the domain"""

    # FIXME Replace with typing.Protocol

    def __init__(
        self, name: str, domain: Any, conn_info: Dict[str, str]
    ) -> None:  # FIXME Any should be Domain
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

        self._subscribers = defaultdict(set)
        self._command_handlers = {}

    @abstractmethod
    def publish(self, message: Dict) -> None:
        """Publish a message with Protean-compatible payload to the configured Message bus.

        Args:
            message (Dict): Command or Event payload
        """

    @abstractmethod
    def get_next(self) -> Dict:
        """Retrieve the next message to process from broker.
        """

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all data in broker instance.

        Useful for clearing cache and running tests.
        """

    def register(
        self,
        initiator_cls: Union[BaseCommand, BaseEvent],
        consumer_cls: Union[BaseCommandHandler, BaseSubscriber],
    ) -> None:
        """Registers Events and Commands with Subscribers/Command Handlers

        Arguments:
            initiator_cls {list} -- One or more Events or Commands
            consumer_cls {Subscriber/CommandHandler} -- The consumer class connected to the Event or Command
        """
        if not isinstance(initiator_cls, Iterable):
            initiator_cls = [initiator_cls]

        for initiator in initiator_cls:
            if initiator.element_type == DomainObjects.EVENT:
                self._subscribers[fully_qualified_name(initiator)].add(consumer_cls)
                logger.debug(
                    f"Registered Subscriber {consumer_cls.__name__} with broker {self.name}"
                )
            else:
                self._command_handlers[fully_qualified_name(initiator)] = consumer_cls
