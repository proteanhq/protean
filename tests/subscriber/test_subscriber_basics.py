"""Tests for BaseSubscriber in core/subscriber.py."""

import pytest

from protean.core.subscriber import BaseSubscriber
from protean.exceptions import IncorrectUsageError, NotSupportedError


class TestSubscriberEdgeCases:
    def test_base_subscriber_cannot_be_instantiated(self):
        """BaseSubscriber direct instantiation guard."""
        with pytest.raises(NotSupportedError, match="cannot be instantiated"):
            BaseSubscriber()

    def test_subscriber_without_stream_raises(self, test_domain):
        """Subscriber without stream raises IncorrectUsageError."""

        class BadSubscriber(BaseSubscriber):
            def __call__(self, payload: dict) -> None:
                pass

        with pytest.raises(IncorrectUsageError, match="associated with an Event"):
            test_domain.register(BadSubscriber, stream=None)
            test_domain.init(traverse=False)

    def test_subscriber_without_broker_raises(self, test_domain):
        """Subscriber without broker raises IncorrectUsageError."""

        class NoBrokerSubscriber(BaseSubscriber):
            def __call__(self, payload: dict) -> None:
                pass

        with pytest.raises(IncorrectUsageError, match="associated with a Broker"):
            test_domain.register(NoBrokerSubscriber, stream="some_stream", broker=None)
            test_domain.init(traverse=False)
