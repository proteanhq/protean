"""Tests for the dead-letter queue operations on the ``Broker`` service and the
``DeadLetterQueuePort`` sub-protocol a ``DEAD_LETTER_QUEUE`` broker subclasses."""

from datetime import UTC, datetime
from typing import Any

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.adapters.broker.redis import RedisBroker
from protean.adapters.broker.redis_pubsub import RedisPubSubBroker
from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.infra.broker import Broker
from protean.infra.registry import brokers as broker_registry
from protean.port.broker import (
    CAPABILITY_PORTS,
    BrokerCapabilities,
    BrokerPort,
    DeadLetterQueuePort,
    DLQEntry,
)
from tests.infra.test_broker_service import StubAdapter
from tests.shared import REDIS_URI

ENTRY = DLQEntry(
    dlq_id="dlq-1",
    original_id="msg-1",
    stream="orders",
    consumer_group="billing",
    payload={"n": 1},
    failure_reason="unknown",
    failed_at="2026-01-01T00:00:00+00:00",
    retry_count=3,
    dlq_stream="orders:dlq",
)
CUTOFF = datetime(2026, 1, 2, tzinfo=UTC)
NAIVE_CUTOFF = datetime(2026, 1, 2)

DLQ_MEMBERS = [
    "dlq_depth",
    "dlq_get",
    "dlq_list",
    "dlq_purge",
    "dlq_replay",
    "dlq_replay_all",
    "dlq_trim",
]


class DLQStubAdapter(StubAdapter, DeadLetterQueuePort):
    """A stub that declares ``DEAD_LETTER_QUEUE`` and records each DLQ call."""

    def __init__(self, name: str, domain: Any, config: Any) -> None:
        super().__init__(
            name,
            domain,
            config,
            BrokerCapabilities.RELIABLE_MESSAGING
            | BrokerCapabilities.DEAD_LETTER_QUEUE,
        )

    def dlq_list(self, dlq_streams: list[str], limit: int = 100) -> list[DLQEntry]:
        self.calls.append(("dlq_list", dlq_streams, limit))
        return [ENTRY]

    def dlq_get(self, dlq_stream: str, dlq_id: str) -> DLQEntry | None:
        self.calls.append(("dlq_get", dlq_stream, dlq_id))
        return ENTRY

    def dlq_replay(self, dlq_stream: str, dlq_id: str, target_stream: str) -> bool:
        self.calls.append(("dlq_replay", dlq_stream, dlq_id, target_stream))
        return True

    def dlq_replay_all(self, dlq_stream: str, target_stream: str) -> int:
        self.calls.append(("dlq_replay_all", dlq_stream, target_stream))
        return 2

    def dlq_purge(self, dlq_stream: str) -> int:
        self.calls.append(("dlq_purge", dlq_stream))
        return 3

    def dlq_trim(self, dlq_stream: str, older_than: datetime) -> int:
        self.calls.append(("dlq_trim", dlq_stream, older_than))
        return 4

    def dlq_depth(self, dlq_stream: str) -> int:
        self.calls.append(("dlq_depth", dlq_stream))
        return 5


class DeclaresDLQWithoutPort(StubAdapter):
    """Declares ``DEAD_LETTER_QUEUE`` but subclasses only ``BrokerPort``."""

    def __init__(self, name: str, domain: Any, config: Any) -> None:
        super().__init__(
            name,
            domain,
            config,
            BrokerCapabilities.RELIABLE_MESSAGING
            | BrokerCapabilities.DEAD_LETTER_QUEUE,
        )


class TestTheCapabilityTable:
    def test_dead_letter_queue_maps_to_dead_letter_queue_port(self):
        assert (
            CAPABILITY_PORTS[BrokerCapabilities.DEAD_LETTER_QUEUE]
            is DeadLetterQueuePort
        )

    def test_the_port_adds_the_seven_operations_to_broker_port(self):
        added = DeadLetterQueuePort.__abstractmethods__ - BrokerPort.__abstractmethods__

        assert sorted(added) == DLQ_MEMBERS

    def test_inline_and_redis_subclass_the_port_and_pubsub_does_not(self):
        assert DeadLetterQueuePort in InlineBroker.__mro__
        assert DeadLetterQueuePort in RedisBroker.__mro__
        assert DeadLetterQueuePort not in RedisPubSubBroker.__mro__

    def test_the_pubsub_broker_has_no_dlq_member(self):
        assert [
            name
            for name in dir(RedisPubSubBroker)
            if name.lstrip("_").startswith("dlq_")
        ] == []


class TestWithoutTheFlag:
    @pytest.fixture
    def adapter(self, test_domain):
        return StubAdapter("stub", test_domain, {"provider": "stub"})

    def test_every_operation_returns_the_empty_answer(self, adapter):
        broker = Broker(adapter)

        assert broker.dlq_list(["orders:dlq"]) == []
        assert broker.dlq_get("orders:dlq", "dlq-1") is None
        assert broker.dlq_replay("orders:dlq", "dlq-1", "orders") is False
        assert broker.dlq_replay_all("orders:dlq", "orders") == 0
        assert broker.dlq_purge("orders:dlq") == 0
        assert broker.dlq_trim("orders:dlq", CUTOFF) == 0
        assert broker.dlq_depth("orders:dlq") == 0
        assert adapter.calls == []

    def test_an_adapter_with_the_methods_is_not_called(self, test_domain):
        """The service reads the flag, not the methods the adapter has."""
        adapter = DLQStubAdapter("stub", test_domain, {"provider": "stub"})
        adapter._capabilities = BrokerCapabilities.RELIABLE_MESSAGING
        broker = Broker(adapter)

        assert broker.dlq_list(["orders:dlq"]) == []
        assert broker.dlq_depth("orders:dlq") == 0
        assert adapter.calls == []

    def test_a_naive_cutoff_is_rejected_without_the_flag(self, adapter):
        with pytest.raises(ValueError, match="timezone-aware"):
            Broker(adapter).dlq_trim("orders:dlq", NAIVE_CUTOFF)


class TestWithTheFlag:
    @pytest.fixture
    def adapter(self, test_domain):
        return DLQStubAdapter("stub", test_domain, {"provider": "stub"})

    def test_every_operation_reaches_the_adapter(self, adapter):
        broker = Broker(adapter)

        assert broker.dlq_list(["orders:dlq"], limit=7) == [ENTRY]
        assert broker.dlq_get("orders:dlq", "dlq-1") == ENTRY
        assert broker.dlq_replay("orders:dlq", "dlq-1", "orders") is True
        assert broker.dlq_replay_all("orders:dlq", "orders") == 2
        assert broker.dlq_purge("orders:dlq") == 3
        assert broker.dlq_trim("orders:dlq", CUTOFF) == 4
        assert broker.dlq_depth("orders:dlq") == 5
        assert adapter.calls == [
            ("dlq_list", ["orders:dlq"], 7),
            ("dlq_get", "orders:dlq", "dlq-1"),
            ("dlq_replay", "orders:dlq", "dlq-1", "orders"),
            ("dlq_replay_all", "orders:dlq", "orders"),
            ("dlq_purge", "orders:dlq"),
            ("dlq_trim", "orders:dlq", CUTOFF),
            ("dlq_depth", "orders:dlq"),
        ]

    def test_a_naive_cutoff_is_rejected_before_the_adapter_is_called(self, adapter):
        with pytest.raises(ValueError, match="timezone-aware"):
            Broker(adapter).dlq_trim("orders:dlq", NAIVE_CUTOFF)

        assert adapter.calls == []


class TestTheInlineAdapterRejectsANaiveCutoff:
    def test_a_direct_call_raises(self, test_domain):
        adapter = InlineBroker("inline", test_domain, {})

        with pytest.raises(ValueError, match="timezone-aware"):
            adapter.dlq_trim("orders:dlq", NAIVE_CUTOFF)


@pytest.mark.redis
class TestTheRedisAdapterRejectsANaiveCutoff:
    def test_a_direct_call_raises(self, test_domain):
        adapter = RedisBroker("redis", test_domain, {"URI": f"{REDIS_URI}/0"})

        with pytest.raises(ValueError, match="timezone-aware"):
            adapter.dlq_trim("orders:dlq", NAIVE_CUTOFF)


@pytest.mark.no_test_domain
class TestADeclaredFlagNeedsThePort:
    @pytest.fixture(autouse=True)
    def registered(self):
        cls = DeclaresDLQWithoutPort
        broker_registry.register("dlq_no_port", f"{cls.__module__}.{cls.__qualname__}")
        yield
        broker_registry._paths.pop("dlq_no_port", None)

    def test_domain_init_names_the_broker_the_flag_and_the_members(self):
        domain = Domain(name="Test")
        domain.config["brokers"]["default"] = {"provider": "dlq_no_port"}

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        assert str(exc.value) == (
            "Broker 'default' declares BrokerCapabilities.DEAD_LETTER_QUEUE, but "
            "DeclaresDLQWithoutPort does not subclass DeadLetterQueuePort. "
            f"It does not implement: {', '.join(DLQ_MEMBERS)}."
        )
