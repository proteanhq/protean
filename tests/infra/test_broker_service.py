"""Tests for the ``Broker`` service and the ``Brokers`` container."""

from collections.abc import Mapping
from typing import Any

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.core.subscriber import BaseSubscriber
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import NotSupportedError, ValidationError
from protean.infra.broker import Broker, is_connection_error
from protean.port.broker import (
    BrokerCapabilities,
    BrokerHealth,
    BrokerMessage,
    BrokerPort,
    ConsumerGroupInfo,
)


class StubAdapter(BrokerPort):
    """A broker adapter that records each call and fails on request.

    It implements ``BrokerPort`` only, not ``BaseBroker``.
    """

    def __init__(
        self,
        name: str,
        domain: Any,
        config: Mapping[str, Any],
        capabilities: BrokerCapabilities = BrokerCapabilities.RELIABLE_MESSAGING,
    ) -> None:
        self.name = name
        self.domain = domain
        self.config = dict(config)
        self._capabilities = capabilities
        self.calls: list[tuple[Any, ...]] = []
        self.publish_errors: list[Exception] = []
        self.reconnect_result = True
        self.healthy = True
        self.ping_result = True
        self.ping_error: Exception | None = None

    @property
    def capabilities(self) -> BrokerCapabilities:
        return self._capabilities

    def publish(self, stream: str, message: dict[str, Any]) -> str:
        self.calls.append(("publish", stream, message))
        if self.publish_errors:
            raise self.publish_errors.pop(0)
        return "msg-1"

    def read(
        self,
        stream: str,
        consumer_group: str,
        limit: int,
        *,
        new_messages: bool = False,
    ) -> list[BrokerMessage]:
        self.calls.append(("read", stream, consumer_group, limit, new_messages))
        return [BrokerMessage("msg-1", {"n": 1})]

    def ack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        self.calls.append(("ack", stream, message_id, consumer_group))
        return True

    def nack(self, stream: str, message_id: str, consumer_group: str) -> bool:
        self.calls.append(("nack", stream, message_id, consumer_group))
        return True

    def create_group(self, stream: str, consumer_group: str) -> None:
        self.calls.append(("create_group", stream, consumer_group))

    def consumer_groups(self) -> dict[str, ConsumerGroupInfo]:
        return {}

    def ping(self) -> bool:
        self.calls.append(("ping",))
        if self.ping_error is not None:
            raise self.ping_error
        return self.ping_result

    def health(self) -> BrokerHealth:
        return BrokerHealth(
            healthy=self.healthy,
            message_counts={"total_messages": 3},
            consumer_groups={"count": 1, "names": ["billing"]},
            details={"region": "local"},
        )

    def get_connection(self) -> object:
        return None

    def reconnect(self) -> bool:
        self.calls.append(("reconnect",))
        return self.reconnect_result

    def clear(self) -> None:
        self.calls.append(("clear",))


def _calls_named(adapter: StubAdapter, name: str) -> list[tuple[Any, ...]]:
    return [call for call in adapter.calls if call[0] == name]


@pytest.fixture
def adapter(test_domain):
    return StubAdapter("stub", test_domain, {"provider": "stub"})


@pytest.fixture
def broker(adapter):
    return Broker(adapter)


class TestPublish:
    def test_empty_message_raises_validation_error(self, broker, adapter):
        with pytest.raises(ValidationError) as exc:
            broker.publish("orders", {})

        assert exc.value.messages == {"message": ["Message cannot be empty"]}
        assert adapter.calls == []

    def test_publish_outside_a_unit_of_work_returns_the_identifier(
        self, broker, adapter
    ):
        assert broker.publish("orders", {"n": 1}) == "msg-1"
        assert adapter.calls == [("publish", "orders", {"n": 1})]

    def test_publish_inside_a_unit_of_work_records_and_sends_nothing(
        self, broker, adapter
    ):
        uow = UnitOfWork()
        uow.start()
        try:
            assert broker.publish("orders", {"n": 1}) is None
            assert uow._messages_to_dispatch == [("orders", {"n": 1}, "stub")]
        finally:
            uow.rollback()

        assert adapter.calls == []


class TestRetryOnce:
    def test_connection_error_reconnects_once_and_retries(self, broker, adapter):
        adapter.publish_errors = [ConnectionError("connection refused")]

        assert broker.publish("orders", {"n": 1}) == "msg-1"
        assert len(_calls_named(adapter, "publish")) == 2
        assert len(_calls_named(adapter, "reconnect")) == 1

    def test_second_connection_error_is_raised(self, broker, adapter):
        adapter.publish_errors = [
            ConnectionError("connection refused"),
            ConnectionError("connection refused again"),
        ]

        with pytest.raises(ConnectionError, match="again"):
            broker.publish("orders", {"n": 1})
        assert len(_calls_named(adapter, "reconnect")) == 1

    def test_failed_reconnect_raises_the_original_error(self, broker, adapter):
        adapter.publish_errors = [ConnectionError("connection refused")]
        adapter.reconnect_result = False

        with pytest.raises(ConnectionError, match="connection refused"):
            broker.publish("orders", {"n": 1})
        assert len(_calls_named(adapter, "publish")) == 1

    def test_other_errors_are_raised_without_a_retry(self, broker, adapter):
        adapter.publish_errors = [ValueError("bad payload")]

        with pytest.raises(ValueError, match="bad payload"):
            broker.publish("orders", {"n": 1})
        assert len(_calls_named(adapter, "publish")) == 1
        assert _calls_named(adapter, "reconnect") == []


class TestIsConnectionError:
    @pytest.mark.parametrize(
        "message",
        ["Connection refused", "read timed out", "Broken pipe", "network down"],
    )
    def test_connection_messages_are_connection_errors(self, message):
        assert is_connection_error(Exception(message)) is True

    @pytest.mark.parametrize("message", ["bad payload", "key not found", ""])
    def test_other_messages_are_not_connection_errors(self, message):
        assert is_connection_error(Exception(message)) is False


received: list[dict[str, Any]] = []


class OrderSubscriber(BaseSubscriber):
    def __call__(self, payload: dict) -> None:
        received.append(payload)


class TestSynchronousDispatch:
    @pytest.fixture(autouse=True)
    def register_subscriber(self, test_domain, broker):
        received.clear()
        test_domain.register(OrderSubscriber, stream="orders")
        broker.register(OrderSubscriber)

    def test_sync_processing_hands_the_message_to_the_subscriber(
        self, test_domain, broker
    ):
        test_domain.config["message_processing"] = "sync"

        broker.publish("orders", {"n": 1})

        assert received == [{"n": 1}]

    def test_async_processing_does_not_dispatch(self, test_domain, broker):
        test_domain.config["message_processing"] = "async"

        broker.publish("orders", {"n": 1})

        assert received == []

    def test_other_streams_are_not_dispatched(self, test_domain, broker):
        test_domain.config["message_processing"] = "sync"

        broker.publish("invoices", {"n": 1})

        assert received == []


class TestCapabilityGates:
    @pytest.fixture
    def adapter(self, test_domain):
        return StubAdapter(
            "stub",
            test_domain,
            {"provider": "stub"},
            capabilities=BrokerCapabilities.SIMPLE_QUEUING
            & ~BrokerCapabilities.CONSUMER_GROUPS,
        )

    def test_read_without_consumer_groups_returns_empty(self, broker, adapter):
        assert broker.read("orders", "billing", 5) == []
        assert adapter.calls == []

    def test_get_next_without_consumer_groups_returns_none(self, broker, adapter):
        assert broker.get_next("orders", "billing") is None
        assert adapter.calls == []

    def test_ack_and_nack_without_ack_nack_return_false(self, broker, adapter):
        assert broker.ack("orders", "msg-1", "billing") is False
        assert broker.nack("orders", "msg-1", "billing") is False
        assert adapter.calls == []


class TestReads:
    def test_read_passes_the_limit(self, broker, adapter):
        assert broker.read("orders", "billing", 5) == [BrokerMessage("msg-1", {"n": 1})]
        assert adapter.calls == [("read", "orders", "billing", 5, False)]

    def test_get_next_reads_one_new_message(self, broker, adapter):
        assert broker.get_next("orders", "billing") == BrokerMessage("msg-1", {"n": 1})
        assert adapter.calls == [("read", "orders", "billing", 1, True)]

    def test_ack_and_nack_forward_with_ack_nack(self, broker, adapter):
        assert broker.ack("orders", "msg-1", "billing") is True
        assert broker.nack("orders", "msg-2", "billing") is True
        assert adapter.calls == [
            ("ack", "orders", "msg-1", "billing"),
            ("nack", "orders", "msg-2", "billing"),
        ]


class TestHealth:
    def test_healthy_broker(self, broker):
        health = broker.health()

        assert health["status"] == "healthy"
        assert health["connected"] is True
        assert health["last_ping_ms"] is not None
        assert health["uptime_seconds"] >= 0
        assert health["details"] == {
            "healthy": True,
            "message_counts": {"total_messages": 3},
            "consumer_groups": {"count": 1, "names": ["billing"]},
            "region": "local",
        }

    def test_connected_but_unhealthy_broker_is_degraded(self, broker, adapter):
        adapter.healthy = False

        health = broker.health()

        assert health["status"] == "degraded"
        assert health["connected"] is True
        assert health["details"]["healthy"] is False

    def test_failed_ping_is_unhealthy(self, broker, adapter):
        adapter.ping_result = False

        health = broker.health()

        assert health["status"] == "unhealthy"
        assert health["connected"] is False

    def test_ping_that_raises_returns_false(self, broker, adapter):
        adapter.ping_error = RuntimeError("socket closed")

        assert broker.ping() is False

        health = broker.health()
        assert health["status"] == "unhealthy"
        assert health["connected"] is False
        assert health["last_ping_ms"] is None


class TestBaseBrokerForwarders:
    def test_operation_missing_from_the_port_raises_not_supported(self, broker):
        with pytest.raises(NotSupportedError, match="does not implement `dlq_list`"):
            broker.dlq_list(["orders:dlq"])

    def test_framework_forwarders_reach_the_adapter(self, broker, adapter):
        broker._create_group("orders", "billing")
        broker.clear()

        assert adapter.calls == [("create_group", "orders", "billing"), ("clear",)]


class TestBrokers:
    def test_domain_brokers_returns_a_broker_service(self, test_domain):
        broker = test_domain.brokers["default"]

        assert isinstance(broker, Broker)
        assert isinstance(broker._adapter, InlineBroker)

    def test_unchanged_config_reuses_the_broker(self, test_domain):
        before = test_domain.brokers["default"]

        test_domain.brokers._initialize()

        assert test_domain.brokers["default"] is before

    def test_changed_config_replaces_the_broker(self, test_domain):
        before = test_domain.brokers["default"]
        test_domain.config["brokers"]["default"] = {
            **before._adapter.config,
            "max_retries": 7,
        }

        test_domain.brokers._initialize()

        after = test_domain.brokers["default"]
        assert after is not before
        assert after._adapter.config["max_retries"] == 7
