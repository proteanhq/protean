"""Tests for Bucket G: Port Contract Consistency.

Finding #18: cache service _get_all/count take only a key pattern.
Finding #19: Broker _get_next() return type matches implementations.
Finding #21: Port abstract methods have complete type hints.
"""

import inspect
from typing import Any, get_type_hints

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.infra.cache import Cache
from protean.port.broker import BaseBroker
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
# Finding #19: Broker _get_next() return type matches implementations
# ---------------------------------------------------------------------------
class TestBrokerGetNextReturnType:
    def test_port_get_next_returns_tuple_or_none(self):
        """Port's get_next declares tuple[str, dict[str, Any]] | None return type."""
        hints = get_type_hints(BaseBroker.get_next)
        assert hints["return"] == tuple[str, dict[str, Any]] | None

    def test_port_private_get_next_returns_tuple_or_none(self):
        """Port's _get_next declares tuple[str, dict[str, Any]] | None return type."""
        hints = get_type_hints(BaseBroker._get_next)
        assert hints["return"] == tuple[str, dict[str, Any]] | None

    def test_inline_broker_get_next_matches_port(self):
        """InlineBroker._get_next return annotation matches the port's.

        Asserts consistency dynamically (the point of Finding #19) rather than
        pinning a literal, so precision improvements to the shared type stay in
        lock-step without a brittle test edit.
        """
        assert (
            get_type_hints(InlineBroker._get_next)["return"]
            == get_type_hints(BaseBroker._get_next)["return"]
        )


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
