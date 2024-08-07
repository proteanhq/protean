from __future__ import annotations

import logging
import logging.config
from abc import ABCMeta, abstractmethod
from collections import defaultdict
from typing import TYPE_CHECKING, Type

from protean.core.subscriber import BaseSubscriber
from protean.utils import Processing

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class BaseBroker(metaclass=ABCMeta):
    """This class outlines the base broker functions, to be satisfied by all implementing brokers.

    It is also a marker interface for registering broker classes with the domain"""

    # FIXME Replace with typing.Protocol

    def __init__(
        self, name: str, domain: "Domain", conn_info: dict[str, str | bool]
    ) -> None:
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

        self._subscribers = defaultdict(set)

    def publish(self, channel: str, message: dict) -> None:
        """Publish a message to the broker.

        Args:
            channel (str): The channel to which the message should be published
            message (dict): The message payload to be published
        """
        self._publish(channel, message)

        if (
            self.domain.config["message_processing"] == Processing.SYNC.value
            and self._subscribers[channel]
        ):
            for subscriber_cls in self._subscribers[channel]:
                subscriber = subscriber_cls()
                subscriber(message)

    @abstractmethod
    def _publish(self, channel: str, message: dict) -> None:
        """Overidden method to publish a message with payload to the configured broker.

        Args:
            channel (str): The channel to which the message should be published
            message (dict): The message payload to be published
        """

    def get_next(self, channel: str) -> dict | None:
        """Retrieve the next message to process from broker.

        Args:
            channel (str): The channel from which to retrieve the message

        Returns:
            dict: The message payload
        """
        return self._get_next(channel)

    @abstractmethod
    def _get_next(self, channel: str) -> dict | None:
        """Overridden method to retrieve the next message to process from broker."""

    @abstractmethod
    def read(self, channel: str, no_of_messages: int) -> list[dict]:
        """Read messages from the broker.

        Args:
            channel (str): The channel from which to read messages
            no_of_messages (int): The number of messages to read

        Returns:
            list[dict]: The list of messages
        """

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all data in broker instance.

        Useful for clearing cache and running tests.
        """

    def register(self, subscriber_cls: Type[BaseSubscriber]) -> None:
        """Registers subscribers to brokers against their channels.

        Arguments:
            subscriber_cls {Subscriber} -- The subscriber class connected to the channel
        """
        channel = subscriber_cls.meta_.channel

        self._subscribers[channel].add(subscriber_cls)

        logger.debug(
            f"Broker {self.name}: Registered Subscriber {subscriber_cls.__name__} for channel {channel}"
        )
