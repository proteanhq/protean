"""Tests for the partition and trim methods on the ``Broker`` service, and the
``PartitioningPort`` and ``StreamRetentionPort`` sub-protocols a broker
subclasses when it declares ``STREAM_PARTITIONING`` or ``STREAM_RETENTION``."""

from typing import Any

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.adapters.broker.redis import RedisBroker
from protean.adapters.broker.redis_pubsub import RedisPubSubBroker
from protean.exceptions import ConfigurationError
from protean.infra.broker import Broker
from protean.port.broker import (
    CAPABILITY_PORTS,
    BrokerCapabilities,
    BrokerMessage,
    LeaseLostError,
    PartitioningPort,
    StreamRetentionPort,
)
from tests.infra.test_broker_service import StubAdapter, _calls_named

MESSAGE = BrokerMessage("1-0", {"n": 1})

PARTITION_CALLS = [
    ("_record_partition", ("cat", "a")),
    ("_partition_keys", ("cat",)),
    ("_reap_partition", ("cat", "a", 0)),
    ("_acquire_partition_lease", ("lease", "gen", "owner", 1000)),
    ("_renew_partition_lease", ("lease", "owner:1", 1000)),
    ("_release_partition_lease", ("lease", "owner:1")),
    ("_read_partition_fenced", ("s", "g", "c", "lease", "owner:1")),
    ("_ack_partition_fenced", ("s", "1-0", "g", "lease", "owner:1")),
    ("_reclaim_partition_pending", ("s", "g", "c")),
]


class PartitioningStubAdapter(StubAdapter, PartitioningPort):
    """A stub that declares ``STREAM_PARTITIONING`` and records each call."""

    def __init__(self, name: str, domain: Any, config: Any) -> None:
        super().__init__(
            name,
            domain,
            config,
            BrokerCapabilities.RELIABLE_MESSAGING
            | BrokerCapabilities.STREAM_PARTITIONING,
        )
        self.partition_errors: list[Exception] = []

    def _record(self, *call: Any) -> None:
        self.calls.append(call)
        if self.partition_errors:
            raise self.partition_errors.pop(0)

    def record_partition(self, category: str, key: str) -> None:
        self._record("record_partition", category, key)

    def partition_keys(self, category: str) -> set[str]:
        self._record("partition_keys", category)
        return {"a", "b"}

    def reap_partition(
        self,
        category: str,
        key: str,
        min_idle_ms: int,
        backfill_suffix: str | None,
    ) -> bool:
        self._record("reap_partition", category, key, min_idle_ms, backfill_suffix)
        return True

    def acquire_partition_lease(
        self, lease_key: str, generation_key: str, owner_id: str, ttl_ms: int
    ) -> int | None:
        self._record(
            "acquire_partition_lease", lease_key, generation_key, owner_id, ttl_ms
        )
        return 7

    def renew_partition_lease(
        self, lease_key: str, fence_token: str, ttl_ms: int
    ) -> bool:
        self._record("renew_partition_lease", lease_key, fence_token, ttl_ms)
        return True

    def release_partition_lease(self, lease_key: str, fence_token: str) -> bool:
        self._record("release_partition_lease", lease_key, fence_token)
        return True

    def read_partition_fenced(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        lease_key: str,
        fence_token: str,
        limit: int,
        new_messages: bool,
    ) -> list[BrokerMessage]:
        self._record(
            "read_partition_fenced",
            stream,
            consumer_group,
            consumer_name,
            lease_key,
            fence_token,
            limit,
            new_messages,
        )
        return [MESSAGE]

    def ack_partition_fenced(
        self,
        stream: str,
        message_id: str,
        consumer_group: str,
        lease_key: str,
        fence_token: str,
    ) -> bool:
        self._record(
            "ack_partition_fenced",
            stream,
            message_id,
            consumer_group,
            lease_key,
            fence_token,
        )
        return True

    def reclaim_partition_pending(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        min_idle_ms: int,
        limit: int,
    ) -> list[BrokerMessage]:
        self._record(
            "reclaim_partition_pending",
            stream,
            consumer_group,
            consumer_name,
            min_idle_ms,
            limit,
        )
        return [MESSAGE]


class RetentionStubAdapter(StubAdapter, StreamRetentionPort):
    """A stub that subclasses ``StreamRetentionPort`` and records each trim."""

    def __init__(
        self,
        name: str,
        domain: Any,
        config: Any,
        capabilities: BrokerCapabilities = (
            BrokerCapabilities.RELIABLE_MESSAGING | BrokerCapabilities.STREAM_RETENTION
        ),
    ) -> None:
        super().__init__(name, domain, config, capabilities)

    def trim(self, stream: str, maxlen: int) -> int:
        self.calls.append(("trim", stream, maxlen))
        return 4


class DeclaresPartitioningWithoutPort(StubAdapter):
    def __init__(self, name: str, domain: Any, config: Any) -> None:
        super().__init__(
            name,
            domain,
            config,
            BrokerCapabilities.RELIABLE_MESSAGING
            | BrokerCapabilities.STREAM_PARTITIONING,
        )


class DeclaresRetentionWithoutPort(StubAdapter):
    def __init__(self, name: str, domain: Any, config: Any) -> None:
        super().__init__(
            name,
            domain,
            config,
            BrokerCapabilities.RELIABLE_MESSAGING | BrokerCapabilities.STREAM_RETENTION,
        )


@pytest.fixture
def partitioning_adapter(test_domain):
    return PartitioningStubAdapter("stub", test_domain, {"provider": "stub"})


class TestTheCapabilityTable:
    def test_partitioning_maps_to_partitioning_port(self):
        assert (
            CAPABILITY_PORTS[BrokerCapabilities.STREAM_PARTITIONING] is PartitioningPort
        )

    def test_retention_maps_to_stream_retention_port(self):
        assert (
            CAPABILITY_PORTS[BrokerCapabilities.STREAM_RETENTION] is StreamRetentionPort
        )

    def test_only_the_redis_streams_broker_subclasses_the_ports(self):
        for port in (PartitioningPort, StreamRetentionPort):
            assert port in RedisBroker.__mro__
            assert port not in InlineBroker.__mro__
            assert port not in RedisPubSubBroker.__mro__


class TestAPartitioningBroker:
    def test_record_partition_forwards_its_arguments(self, partitioning_adapter):
        assert Broker(partitioning_adapter)._record_partition("cat", "a") is None
        assert partitioning_adapter.calls == [("record_partition", "cat", "a")]

    def test_partition_keys_returns_the_adapter_keys(self, partitioning_adapter):
        assert Broker(partitioning_adapter)._partition_keys("cat") == {"a", "b"}
        assert partitioning_adapter.calls == [("partition_keys", "cat")]

    def test_reap_partition_defaults_to_no_backfill_lane(self, partitioning_adapter):
        assert Broker(partitioning_adapter)._reap_partition("cat", "a", 50) is True
        assert partitioning_adapter.calls == [("reap_partition", "cat", "a", 50, None)]

    def test_reap_partition_passes_the_backfill_suffix(self, partitioning_adapter):
        Broker(partitioning_adapter)._reap_partition("cat", "a", 50, "backfill")
        assert partitioning_adapter.calls == [
            ("reap_partition", "cat", "a", 50, "backfill")
        ]

    def test_lease_operations_forward_their_arguments(self, partitioning_adapter):
        broker = Broker(partitioning_adapter)

        assert broker._acquire_partition_lease("lease", "gen", "owner", 1000) == 7
        assert broker._renew_partition_lease("lease", "owner:7", 2000) is True
        assert broker._release_partition_lease("lease", "owner:7") is True

        assert partitioning_adapter.calls == [
            ("acquire_partition_lease", "lease", "gen", "owner", 1000),
            ("renew_partition_lease", "lease", "owner:7", 2000),
            ("release_partition_lease", "lease", "owner:7"),
        ]

    def test_read_partition_fenced_defaults(self, partitioning_adapter):
        result = Broker(partitioning_adapter)._read_partition_fenced(
            "s", "g", "c", "lease", "owner:7"
        )

        assert result == [MESSAGE]
        assert partitioning_adapter.calls == [
            ("read_partition_fenced", "s", "g", "c", "lease", "owner:7", 1, True)
        ]

    def test_read_partition_fenced_passes_limit_and_new_messages(
        self, partitioning_adapter
    ):
        Broker(partitioning_adapter)._read_partition_fenced(
            "s", "g", "c", "lease", "owner:7", limit=5, new_messages=False
        )
        assert partitioning_adapter.calls == [
            ("read_partition_fenced", "s", "g", "c", "lease", "owner:7", 5, False)
        ]

    def test_ack_partition_fenced_forwards_the_message_id(self, partitioning_adapter):
        assert (
            Broker(partitioning_adapter)._ack_partition_fenced(
                "s", "1-0", "g", "lease", "owner:7"
            )
            is True
        )
        assert partitioning_adapter.calls == [
            ("ack_partition_fenced", "s", "1-0", "g", "lease", "owner:7")
        ]

    def test_reclaim_partition_pending_defaults(self, partitioning_adapter):
        result = Broker(partitioning_adapter)._reclaim_partition_pending("s", "g", "c")

        assert result == [MESSAGE]
        assert partitioning_adapter.calls == [
            ("reclaim_partition_pending", "s", "g", "c", 0, 100)
        ]

    def test_reclaim_partition_pending_passes_idle_and_limit(
        self, partitioning_adapter
    ):
        Broker(partitioning_adapter)._reclaim_partition_pending(
            "s", "g", "c", min_idle_ms=30, limit=10
        )
        assert partitioning_adapter.calls == [
            ("reclaim_partition_pending", "s", "g", "c", 30, 10)
        ]

    @pytest.mark.parametrize(
        "error",
        [LeaseLostError("lease lost"), ConnectionError("connection reset")],
        ids=["lease-lost", "connection-error"],
    )
    @pytest.mark.parametrize(("operation", "args"), PARTITION_CALLS)
    def test_an_error_is_raised_after_one_call_without_a_retry(
        self, partitioning_adapter, operation, args, error
    ):
        partitioning_adapter.partition_errors = [error]

        with pytest.raises(type(error)):
            getattr(Broker(partitioning_adapter), operation)(*args)

        assert len(_calls_named(partitioning_adapter, operation.lstrip("_"))) == 1
        assert _calls_named(partitioning_adapter, "reconnect") == []


class TestTrim:
    def test_an_inline_broker_trims_nothing(self, test_domain):
        test_domain.init(traverse=False)
        broker = test_domain.brokers["default"]
        assert isinstance(broker._adapter, InlineBroker)
        for n in range(3):
            broker.publish("s", {"n": n})

        assert broker._trim("s", 1) == 0
        assert len(broker._adapter._messages["s"]) == 3

    def test_a_retention_broker_returns_what_the_adapter_trims(self, test_domain):
        adapter = RetentionStubAdapter("stub", test_domain, {"provider": "stub"})

        assert Broker(adapter)._trim("s", 10) == 4
        assert adapter.calls == [("trim", "s", 10)]

    def test_the_adapter_trim_is_not_called_without_the_flag(self, test_domain):
        adapter = RetentionStubAdapter(
            "stub",
            test_domain,
            {"provider": "stub"},
            BrokerCapabilities.RELIABLE_MESSAGING,
        )

        assert Broker(adapter)._trim("s", 10) == 0
        assert _calls_named(adapter, "trim") == []


class TestADeclaredCapabilityNeedsItsPort:
    def test_partitioning_without_the_port_is_rejected(self, test_domain):
        adapter = DeclaresPartitioningWithoutPort(
            "stub", test_domain, {"provider": "stub"}
        )

        with pytest.raises(ConfigurationError) as exc:
            Broker(adapter)

        assert str(exc.value) == (
            "Broker 'stub' declares BrokerCapabilities.STREAM_PARTITIONING, but "
            "DeclaresPartitioningWithoutPort does not subclass PartitioningPort. "
            "It does not implement: ack_partition_fenced, acquire_partition_lease, "
            "partition_keys, read_partition_fenced, reap_partition, "
            "reclaim_partition_pending, record_partition, release_partition_lease, "
            "renew_partition_lease."
        )

    def test_retention_without_the_port_is_rejected(self, test_domain):
        adapter = DeclaresRetentionWithoutPort(
            "stub", test_domain, {"provider": "stub"}
        )

        with pytest.raises(ConfigurationError) as exc:
            Broker(adapter)

        assert str(exc.value) == (
            "Broker 'stub' declares BrokerCapabilities.STREAM_RETENTION, but "
            "DeclaresRetentionWithoutPort does not subclass StreamRetentionPort. "
            "It does not implement: trim."
        )
