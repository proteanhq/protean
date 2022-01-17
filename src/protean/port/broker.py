from __future__ import annotations

import logging
import logging.config

from abc import ABCMeta, abstractmethod
from collections import defaultdict
from collections.abc import Iterable
from typing import Any, Dict, Union

from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.subscriber import BaseSubscriber
from protean.utils import DomainObjects, fully_qualified_name

logger = logging.getLogger(__name__)


class BaseBroker(metaclass=ABCMeta):
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
        """Retrieve the next message to process from broker."""

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
