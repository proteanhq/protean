"""Tests for Bucket G: Port Contract Consistency.

Finding #18: cache service _get_all/count take only a key pattern.
Finding #19: Broker read/get_next return types and adapter signatures match BrokerPort.
Finding #21: Port abstract methods have complete type hints.
"""

import inspect
from typing import get_type_hints

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.adapters.broker.redis import RedisBroker
from protean.adapters.broker.redis_pubsub import RedisPubSubBroker
from protean.infra.broker import Broker
from protean.infra.cache import Cache
from protean.port.broker import BrokerCapabilities, BrokerMessage, BrokerPort
from protean.port.cache import CachePatternPort, CachePort, CacheTTLPort
from protean.port.provider import BaseProvider, ProviderPort, RawQueryProviderPort


# ---------------------------------------------------------------------------
# Finding #18: Cache service signatures take only a key pattern
# ---------------------------------------------------------------------------
class TestCacheParameterConsistency:
    def test_service__get_all_takes_only_key_pattern(self):
        """`Cache._get_all(key_pattern)` takes no pagination params."""
        sig = inspect.signature(Cache._get_all)
        param_names = [p for p in sig.parameters if p != "self"]
        assert param_names == ["key_pattern"]

    def test_service_count_has_no_extra_parameters(self):
        """`Cache.count(key_pattern)` takes no extra params."""
        sig = inspect.signature(Cache.count)
        param_names = [p for p in sig.parameters if p != "self"]
        assert param_names == ["key_pattern"]


# ---------------------------------------------------------------------------
# Finding #19: Broker read and get_next return types match the port
# ---------------------------------------------------------------------------
BROKER_ADAPTERS = (InlineBroker, RedisBroker, RedisPubSubBroker)

# The members of ``BrokerPort`` an adapter implements, without the constructor.
BROKER_PORT_METHODS = (
    "ping",
    "health",
    "get_connection",
    "close",
    "clear",
    "reconnect",
    "publish",
    "read",
    "ack",
    "nack",
    "create_group",
    "consumer_groups",
    "mark_subscription_owned",
    "remove_stale_consumers",
    "reclaim_idle_pending",
)


class TestBrokerGetNextReturnType:
    def test_service_get_next_returns_message_or_none(self):
        """The service's get_next declares BrokerMessage | None as its return type."""
        hints = get_type_hints(Broker.get_next)
        assert hints["return"] == BrokerMessage | None

    def test_port_read_returns_list_of_messages(self):
        """BrokerPort.read declares list[BrokerMessage] as its return type."""
        hints = get_type_hints(BrokerPort.read)
        assert hints["return"] == list[BrokerMessage]

    def test_service_read_matches_port(self):
        """The service's read returns what the port's read returns."""
        assert (
            get_type_hints(Broker.read)["return"]
            == get_type_hints(BrokerPort.read)["return"]
        )

    @pytest.mark.parametrize("adapter_cls", BROKER_ADAPTERS)
    def test_adapter_read_matches_port(self, adapter_cls):
        """Each adapter's read return annotation matches the port's.

        Asserts consistency dynamically (the point of Finding #19) rather than
        pinning a literal, so precision improvements to the shared type stay in
        lock-step without a brittle test edit.
        """
        assert (
            get_type_hints(adapter_cls.read)["return"]
            == get_type_hints(BrokerPort.read)["return"]
        )


class TestBrokerParameterConsistency:
    @pytest.mark.parametrize("adapter_cls", BROKER_ADAPTERS)
    @pytest.mark.parametrize("method_name", BROKER_PORT_METHODS)
    def test_adapter_parameters_match_port(self, adapter_cls, method_name):
        """Each adapter method takes the parameters the port declares, by name."""
        port_params = list(
            inspect.signature(getattr(BrokerPort, method_name)).parameters
        )
        adapter_params = list(
            inspect.signature(getattr(adapter_cls, method_name)).parameters
        )
        assert adapter_params == port_params

    @pytest.mark.parametrize("adapter_cls", BROKER_ADAPTERS)
    @pytest.mark.parametrize(
        "method_name", [m for m in BROKER_PORT_METHODS if m != "get_connection"]
    )
    def test_adapter_type_hints_match_port(self, adapter_cls, method_name):
        """Each adapter method has the type hints the port declares.

        ``get_connection`` is left out: the Redis adapters narrow its ``object``
        return to ``redis.Redis[Any]``, a generic only the type stubs define,
        so ``get_type_hints`` cannot evaluate it at runtime.
        """
        assert get_type_hints(getattr(adapter_cls, method_name)) == get_type_hints(
            getattr(BrokerPort, method_name)
        )

    @pytest.mark.parametrize("adapter_cls", BROKER_ADAPTERS)
    def test_adapter_subclasses_port(self, adapter_cls):
        """Each adapter subclasses BrokerPort explicitly."""
        assert BrokerPort in adapter_cls.__mro__


# ---------------------------------------------------------------------------
# Finding #21: Port abstract methods have type hints
# ---------------------------------------------------------------------------
CACHE_PORT_MEMBERS = sorted(
    (port.__name__, name)
    for port in (CachePort, CacheTTLPort, CachePatternPort)
    for name in port.__abstractmethods__
)


class TestCachePortTypeHints:
    def test_every_cache_port_declares_abstract_members(self):
        ports = {port for port, _name in CACHE_PORT_MEMBERS}
        assert ports == {"CachePort", "CacheTTLPort", "CachePatternPort"}

    @pytest.mark.parametrize(("port_name", "member"), CACHE_PORT_MEMBERS)
    def test_member_has_return_type(self, port_name, member):
        port = {
            "CachePort": CachePort,
            "CacheTTLPort": CacheTTLPort,
            "CachePatternPort": CachePatternPort,
        }[port_name]
        attribute = getattr(port, member)
        function = attribute.fget if isinstance(attribute, property) else attribute
        hints = get_type_hints(function)
        assert "return" in hints


class TestBrokerPortTypeHints:
    @pytest.mark.parametrize("method_name", BROKER_PORT_METHODS)
    def test_method_has_return_type(self, method_name):
        hints = get_type_hints(getattr(BrokerPort, method_name))
        assert "return" in hints

    def test_capabilities_has_return_type(self):
        hints = get_type_hints(BrokerPort.capabilities.fget)
        assert hints["return"] is BrokerCapabilities


PROVIDER_PORT_MEMBERS = sorted(
    (port.__name__, name)
    for port in (ProviderPort, RawQueryProviderPort)
    for name in port.__abstractmethods__
)


class TestProviderPortTypeHints:
    """Each abstract member names its return type.

    The annotations are read as written, because several name classes the
    port imports only for type checking.
    """

    def test_every_provider_port_declares_abstract_members(self):
        ports = {port for port, _name in PROVIDER_PORT_MEMBERS}
        assert ports == {"ProviderPort", "RawQueryProviderPort"}

    @pytest.mark.parametrize(("port_name", "member"), PROVIDER_PORT_MEMBERS)
    def test_member_has_return_type(self, port_name, member):
        port = {
            "ProviderPort": ProviderPort,
            "RawQueryProviderPort": RawQueryProviderPort,
        }[port_name]
        attribute = getattr(port, member)
        function = attribute.fget if isinstance(attribute, property) else attribute
        assert "return" in function.__annotations__

    @pytest.mark.parametrize("member", ["close", "create_schema", "drop_schema"])
    def test_optional_member_has_return_type(self, member):
        assert "return" in getattr(ProviderPort, member).__annotations__

    def test_base_provider_raw_has_return_type(self):
        hints = get_type_hints(BaseProvider.raw)
        assert "return" in hints
