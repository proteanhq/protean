"""Tests for the blocking reads on the ``Broker`` service and the
``BlockingReadPort`` sub-protocol a ``BLOCKING_READ`` broker subclasses."""

import time
from collections.abc import Sequence
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
    BlockingReadPort,
    BrokerCapabilities,
    BrokerMessage,
)
from tests.infra.test_broker_service import StubAdapter, _calls_named

MESSAGE = BrokerMessage("msg-1", {"n": 1})


class BlockingStubAdapter(StubAdapter, BlockingReadPort):
    """A stub that declares ``BLOCKING_READ`` and records each blocking read."""

    def __init__(self, name: str, domain: Any, config: Any) -> None:
        super().__init__(
            name,
            domain,
            config,
            BrokerCapabilities.RELIABLE_MESSAGING | BrokerCapabilities.BLOCKING_READ,
        )
        self.blocking_errors: list[Exception] = []

    def _next_blocking_error(self) -> None:
        if self.blocking_errors:
            raise self.blocking_errors.pop(0)

    def read_blocking(
        self,
        stream: str,
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        limit: int = 1,
    ) -> list[BrokerMessage]:
        self.calls.append(
            ("read_blocking", stream, consumer_group, consumer_name, timeout_ms, limit)
        )
        self._next_blocking_error()
        return [MESSAGE]

    def read_blocking_streams(
        self,
        streams: Sequence[str],
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int = 5000,
        limit: int = 1,
    ) -> dict[str, list[BrokerMessage]]:
        self.calls.append(
            (
                "read_blocking_streams",
                list(streams),
                consumer_group,
                consumer_name,
                timeout_ms,
                limit,
            )
        )
        self._next_blocking_error()
        return {stream: [MESSAGE] for stream in streams}


class DeclaresBlockingReadWithoutPort(StubAdapter):
    """Declares ``BLOCKING_READ`` but subclasses only ``BrokerPort``."""

    closed: list[str] = []

    def __init__(self, name: str, domain: Any, config: Any) -> None:
        super().__init__(
            name,
            domain,
            config,
            BrokerCapabilities.RELIABLE_MESSAGING | BrokerCapabilities.BLOCKING_READ,
        )

    def close(self) -> None:
        DeclaresBlockingReadWithoutPort.closed.append(self.name)


class DeclaresBlockingReadWithMethodsWithoutPort(DeclaresBlockingReadWithoutPort):
    """Has both blocking reads but subclasses only ``BrokerPort``."""

    read_blocking = BlockingStubAdapter.read_blocking
    read_blocking_streams = BlockingStubAdapter.read_blocking_streams


class RejectedAdapterCloseFails(DeclaresBlockingReadWithoutPort):
    """Declares ``BLOCKING_READ`` without the port, and fails to close."""

    def close(self) -> None:
        raise RuntimeError("close failed")


class SubclassesPortWithoutFlag(BlockingStubAdapter):
    """Subclasses ``BlockingReadPort`` without declaring ``BLOCKING_READ``."""

    def __init__(self, name: str, domain: Any, config: Any) -> None:
        super().__init__(name, domain, config)
        self._capabilities = BrokerCapabilities.RELIABLE_MESSAGING


@pytest.fixture
def adapter(test_domain):
    return StubAdapter("stub", test_domain, {"provider": "stub"})


@pytest.fixture
def blocking_adapter(test_domain):
    return BlockingStubAdapter("stub", test_domain, {"provider": "stub"})


class TestTheCapabilityTable:
    def test_blocking_read_maps_to_blocking_read_port(self):
        assert CAPABILITY_PORTS[BrokerCapabilities.BLOCKING_READ] is BlockingReadPort

    def test_only_the_redis_streams_broker_subclasses_the_port(self):
        assert BlockingReadPort in RedisBroker.__mro__
        assert BlockingReadPort not in InlineBroker.__mro__
        assert BlockingReadPort not in RedisPubSubBroker.__mro__


class TestFallbackWithoutBlockingRead:
    def test_read_blocking_reads_once_with_the_limit(self, adapter):
        result = Broker(adapter).read_blocking("s", "g", "c", timeout_ms=1000, limit=3)

        assert result == [MESSAGE]
        assert adapter.calls == [("read", "s", "g", 3, False)]

    def test_read_blocking_streams_reads_each_stream_once_in_order(self, adapter):
        result = Broker(adapter).read_blocking_streams(
            ["a", "b"], "g", "c", timeout_ms=1000, limit=4
        )

        assert result == {"a": [MESSAGE], "b": [MESSAGE]}
        assert list(result) == ["a", "b"]
        assert adapter.calls == [
            ("read", "a", "g", 4, False),
            ("read", "b", "g", 4, False),
        ]

    def test_inline_read_blocking_returns_at_once_with_what_read_returns(
        self, test_domain
    ):
        broker = test_domain.brokers["default"]
        identifier = broker.publish("s", {"n": 1})

        start = time.monotonic()
        result = broker.read_blocking("s", "g", "c", timeout_ms=1000)
        elapsed = time.monotonic() - start

        assert result == [(identifier, {"n": 1})]
        assert elapsed < 0.5
        # The read consumed the message for the group, as ``read`` does.
        assert broker.read("s", "g", 1) == []

    def test_inline_read_blocking_streams_keys_every_stream(self, test_domain):
        broker = test_domain.brokers["default"]
        first = broker.publish("a", {"n": 1})
        second = broker.publish("b", {"n": 2})

        start = time.monotonic()
        result = broker.read_blocking_streams(["a", "b"], "g", "c", timeout_ms=1000)
        elapsed = time.monotonic() - start

        assert result == {"a": [(first, {"n": 1})], "b": [(second, {"n": 2})]}
        assert list(result) == ["a", "b"]
        assert elapsed < 0.5

    def test_connection_error_reconnects_and_reads_again(self, adapter):
        reads = [ConnectionError("connection reset")]
        original_read = adapter.read

        def read_failing_once(*args: Any, **kwargs: Any) -> list[BrokerMessage]:
            if reads:
                adapter.calls.append(("read_failed",))
                raise reads.pop(0)
            return original_read(*args, **kwargs)

        adapter.read = read_failing_once

        result = Broker(adapter).read_blocking_streams(["a", "b"], "g", "c")

        assert result == {"a": [MESSAGE], "b": [MESSAGE]}
        assert len(_calls_named(adapter, "reconnect")) == 1
        assert len(_calls_named(adapter, "read")) == 2


class TestNoStreams:
    def test_empty_streams_returns_empty_dict_without_reading(self, adapter):
        assert Broker(adapter).read_blocking_streams([], "g", "c") == {}
        assert adapter.calls == []

    def test_empty_streams_skips_a_blocking_read_adapter(self, blocking_adapter):
        assert Broker(blocking_adapter).read_blocking_streams([], "g", "c") == {}
        assert blocking_adapter.calls == []


class TestBlockingReadAdapter:
    def test_read_blocking_passes_timeout_and_limit(self, blocking_adapter):
        result = Broker(blocking_adapter).read_blocking(
            "s", "g", "c", timeout_ms=750, limit=3
        )

        assert result == [MESSAGE]
        assert blocking_adapter.calls == [("read_blocking", "s", "g", "c", 750, 3)]

    def test_read_blocking_streams_passes_timeout_and_limit(self, blocking_adapter):
        result = Broker(blocking_adapter).read_blocking_streams(
            ["a", "b"], "g", "c", timeout_ms=750, limit=3
        )

        assert result == {"a": [MESSAGE], "b": [MESSAGE]}
        assert blocking_adapter.calls == [
            ("read_blocking_streams", ["a", "b"], "g", "c", 750, 3)
        ]

    @pytest.mark.parametrize(
        ("operation", "args"),
        [("read_blocking", ("s",)), ("read_blocking_streams", (["a", "b"],))],
    )
    def test_connection_error_reconnects_and_retries_once(
        self, blocking_adapter, operation, args
    ):
        blocking_adapter.blocking_errors = [ConnectionError("connection gone")]

        result = getattr(Broker(blocking_adapter), operation)(
            *args, "g", "c", timeout_ms=750, limit=3
        )

        assert result
        assert len(_calls_named(blocking_adapter, "reconnect")) == 1
        reads = _calls_named(blocking_adapter, operation)
        assert len(reads) == 2
        assert reads[0] == reads[1]

    @pytest.mark.parametrize(
        ("operation", "args"),
        [("read_blocking", ("s",)), ("read_blocking_streams", (["a", "b"],))],
    )
    def test_failed_reconnect_raises_the_error(self, blocking_adapter, operation, args):
        blocking_adapter.blocking_errors = [ConnectionError("connection gone")]
        blocking_adapter.reconnect_result = False

        with pytest.raises(ConnectionError, match="connection gone"):
            getattr(Broker(blocking_adapter), operation)(*args, "g", "c")
        assert len(_calls_named(blocking_adapter, operation)) == 1

    @pytest.mark.parametrize(
        ("operation", "args"),
        [("read_blocking", ("s",)), ("read_blocking_streams", (["a", "b"],))],
    )
    def test_other_errors_are_raised_without_a_retry(
        self, blocking_adapter, operation, args
    ):
        blocking_adapter.blocking_errors = [ValueError("bad")]

        with pytest.raises(ValueError, match="bad"):
            getattr(Broker(blocking_adapter), operation)(*args, "g", "c")
        assert len(_calls_named(blocking_adapter, operation)) == 1
        assert _calls_named(blocking_adapter, "reconnect") == []


class TestTheCapabilityCheckIsOneWay:
    def test_an_undeclared_port_is_accepted_and_falls_back_to_read(self, test_domain):
        adapter = SubclassesPortWithoutFlag("stub", test_domain, {"provider": "stub"})

        result = Broker(adapter).read_blocking("s", "g", "c", limit=2)

        assert result == [MESSAGE]
        assert adapter.calls == [("read", "s", "g", 2, False)]


@pytest.mark.no_test_domain
class TestADeclaredCapabilityNeedsItsPort:
    @pytest.fixture(autouse=True)
    def registered(self):
        DeclaresBlockingReadWithoutPort.closed = []
        for provider, cls in self.PROVIDERS.items():
            broker_registry.register(provider, f"{cls.__module__}.{cls.__qualname__}")
        yield
        for provider in self.PROVIDERS:
            broker_registry._paths.pop(provider, None)

    PROVIDERS = {
        "no_port": DeclaresBlockingReadWithoutPort,
        "methods_no_port": DeclaresBlockingReadWithMethodsWithoutPort,
        "close_fails": RejectedAdapterCloseFails,
    }

    def test_domain_init_names_the_broker_the_flag_and_the_members(self):
        domain = Domain(name="Test")
        domain.config["brokers"]["default"] = {"provider": "no_port"}

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        message = str(exc.value)
        assert message == (
            "Broker 'default' declares BrokerCapabilities.BLOCKING_READ, but "
            "DeclaresBlockingReadWithoutPort does not subclass BlockingReadPort. "
            "It does not implement: read_blocking, read_blocking_streams."
        )

    def test_the_rejected_adapter_is_closed(self):
        domain = Domain(name="Test")
        domain.config["brokers"]["default"] = {"provider": "no_port"}

        with pytest.raises(ConfigurationError):
            domain.init(traverse=False)

        assert DeclaresBlockingReadWithoutPort.closed == ["default"]

    def test_an_adapter_with_both_methods_still_needs_the_port(self):
        domain = Domain(name="Test")
        domain.config["brokers"]["default"] = {"provider": "methods_no_port"}

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        assert str(exc.value) == (
            "Broker 'default' declares BrokerCapabilities.BLOCKING_READ, but "
            "DeclaresBlockingReadWithMethodsWithoutPort does not subclass "
            "BlockingReadPort."
        )

    def test_a_close_failure_does_not_hide_the_configuration_error(self, caplog):
        domain = Domain(name="Test")
        domain.config["brokers"]["default"] = {"provider": "close_fails"}

        with pytest.raises(ConfigurationError, match="does not subclass"):
            domain.init(traverse=False)

        events = [record.getMessage() for record in caplog.records]
        assert "broker.init.rejected_adapter_close_failed" in events
