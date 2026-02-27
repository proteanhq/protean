"""Tests that broker dispatch routes messages to the designated broker,
not broadcast to all brokers.

Fix #3 from audit: UoW should route each message to its intended broker
instead of broadcasting to every configured broker.
"""

import pytest

from protean.core.unit_of_work import UnitOfWork
from protean.domain import Domain

from ..elements import Person, PersonAdded


@pytest.mark.no_test_domain
class TestBrokerRouting:
    """Test message routing in a multi-broker domain setup."""

    @pytest.fixture
    def multi_broker_domain(self):
        """Create a domain with two inline brokers: 'default' and 'secondary'."""
        domain = Domain(name="MultiBrokerTest")
        domain.config["brokers"] = {
            "default": {"provider": "inline"},
            "secondary": {"provider": "inline"},
        }
        domain.config["command_processing"] = "sync"
        domain.config["event_processing"] = "sync"
        domain.config["message_processing"] = "sync"

        domain.register(Person)
        domain.register(PersonAdded, part_of=Person)
        domain.init(traverse=False)

        with domain.domain_context():
            yield domain

    def test_specific_broker_publish_routes_to_that_broker_only(
        self, multi_broker_domain
    ):
        """Publishing via a specific broker within a UoW should only
        deliver to that broker, not all brokers."""
        default_broker = multi_broker_domain.brokers["default"]
        secondary_broker = multi_broker_domain.brokers["secondary"]
        stream = "test_stream"
        message = {"key": "value_for_default"}

        with UnitOfWork():
            # Publish to the default broker specifically
            default_broker.publish(stream, message)

        # Message should be in the default broker
        result = default_broker.get_next(stream, "test_group")
        assert result is not None
        _, retrieved = result
        assert retrieved == message

        # Message should NOT be in the secondary broker
        result = secondary_broker.get_next(stream, "test_group")
        assert result is None

    def test_secondary_broker_publish_routes_to_secondary_only(
        self, multi_broker_domain
    ):
        """Publishing via the secondary broker should only deliver
        to the secondary broker."""
        default_broker = multi_broker_domain.brokers["default"]
        secondary_broker = multi_broker_domain.brokers["secondary"]
        stream = "test_stream"
        message = {"key": "value_for_secondary"}

        with UnitOfWork():
            # Publish to the secondary broker specifically
            secondary_broker.publish(stream, message)

        # Message should NOT be in the default broker
        result = default_broker.get_next(stream, "test_group")
        assert result is None

        # Message should be in the secondary broker
        result = secondary_broker.get_next(stream, "test_group")
        assert result is not None
        _, retrieved = result
        assert retrieved == message

    def test_different_messages_to_different_brokers(self, multi_broker_domain):
        """Different messages published to different brokers within the
        same UoW should each arrive at their intended broker."""
        default_broker = multi_broker_domain.brokers["default"]
        secondary_broker = multi_broker_domain.brokers["secondary"]
        stream = "test_stream"
        msg_default = {"target": "default"}
        msg_secondary = {"target": "secondary"}

        with UnitOfWork():
            default_broker.publish(stream, msg_default)
            secondary_broker.publish(stream, msg_secondary)

        # Each broker should have exactly one message — its own
        result_default = default_broker.get_next(stream, "test_group")
        assert result_default is not None
        assert result_default[1] == msg_default

        result_secondary = secondary_broker.get_next(stream, "test_group")
        assert result_secondary is not None
        assert result_secondary[1] == msg_secondary

        # No extra messages (no cross-broadcast)
        assert default_broker.get_next(stream, "test_group") is None
        assert secondary_broker.get_next(stream, "test_group") is None

    def test_domain_brokers_publish_routes_to_default(self, multi_broker_domain):
        """Publishing via domain.brokers.publish() (the aggregator) should
        route to the default broker."""
        default_broker = multi_broker_domain.brokers["default"]
        secondary_broker = multi_broker_domain.brokers["secondary"]
        stream = "test_stream"
        message = {"via": "aggregator"}

        with UnitOfWork():
            multi_broker_domain.brokers.publish(stream, message)

        # Should arrive at the default broker
        result = default_broker.get_next(stream, "test_group")
        assert result is not None
        assert result[1] == message

        # Should NOT be duplicated to the secondary broker
        assert secondary_broker.get_next(stream, "test_group") is None

    def test_publish_outside_uow_routes_to_specific_broker(self, multi_broker_domain):
        """Publishing outside a UoW should also route to the specific broker."""
        default_broker = multi_broker_domain.brokers["default"]
        secondary_broker = multi_broker_domain.brokers["secondary"]
        stream = "test_stream"

        # Publish directly to secondary (outside UoW)
        secondary_broker.publish(stream, {"direct": "secondary"})

        assert secondary_broker.get_next(stream, "test_group") is not None
        assert default_broker.get_next(stream, "test_group") is None
