"""Tests for Bucket G: Port Contract Consistency.

Finding #18: Redis cache get_all/count parameter names match port.
Finding #19: Broker _get_next() return type matches implementations.
Finding #21: Port abstract methods have complete type hints.
"""

import inspect
from typing import get_type_hints

from protean.adapters.broker.inline import InlineBroker
from protean.adapters.cache.memory import MemoryCache
from protean.port.broker import BaseBroker
from protean.port.cache import BaseCache
from protean.port.provider import BaseProvider


# ---------------------------------------------------------------------------
# Finding #18: Cache adapter signatures match port
# ---------------------------------------------------------------------------
class TestCacheParameterConsistency:
    def test_port_get_all_uses_size_parameter(self):
        """Port declares get_all with 'size' parameter."""
        sig = inspect.signature(BaseCache.get_all)
        assert "size" in sig.parameters
        assert "count" not in sig.parameters

    def test_memory_cache_get_all_uses_size_parameter(self):
        """MemoryCache.get_all uses 'size' matching the port."""
        sig = inspect.signature(MemoryCache.get_all)
        assert "size" in sig.parameters
        assert "count" not in sig.parameters

    def test_port_count_has_no_extra_parameters(self):
        """Port declares count(self, key_pattern) with no extra params."""
        sig = inspect.signature(BaseCache.count)
        param_names = [p for p in sig.parameters if p != "self"]
        assert param_names == ["key_pattern"]

    def test_memory_cache_count_matches_port(self):
        """MemoryCache.count matches port signature."""
        sig = inspect.signature(MemoryCache.count)
        param_names = [p for p in sig.parameters if p != "self"]
        assert param_names == ["key_pattern"]


# ---------------------------------------------------------------------------
# Finding #19: Broker _get_next() return type matches implementations
# ---------------------------------------------------------------------------
class TestBrokerGetNextReturnType:
    def test_port_get_next_returns_tuple_or_none(self):
        """Port's get_next declares tuple[str, dict] | None return type."""
        hints = get_type_hints(BaseBroker.get_next)
        assert hints["return"] == tuple[str, dict] | None

    def test_port_private_get_next_returns_tuple_or_none(self):
        """Port's _get_next declares tuple[str, dict] | None return type."""
        hints = get_type_hints(BaseBroker._get_next)
        assert hints["return"] == tuple[str, dict] | None

    def test_inline_broker_get_next_matches_port(self):
        """InlineBroker._get_next return annotation matches port."""
        hints = get_type_hints(InlineBroker._get_next)
        assert hints["return"] == tuple[str, dict] | None


# ---------------------------------------------------------------------------
# Finding #21: Port abstract methods have type hints
# ---------------------------------------------------------------------------
class TestCachePortTypeHints:
    def test_ping_has_return_type(self):
        hints = get_type_hints(BaseCache.ping)
        assert "return" in hints

    def test_get_connection_has_return_type(self):
        hints = get_type_hints(BaseCache.get_connection)
        assert "return" in hints

    def test_get_has_return_type(self):
        hints = get_type_hints(BaseCache.get)
        assert "return" in hints

    def test_get_all_has_return_type(self):
        hints = get_type_hints(BaseCache.get_all)
        assert "return" in hints

    def test_count_has_return_type(self):
        hints = get_type_hints(BaseCache.count)
        assert "return" in hints

    def test_remove_has_return_type(self):
        hints = get_type_hints(BaseCache.remove)
        assert "return" in hints

    def test_flush_all_has_return_type(self):
        hints = get_type_hints(BaseCache.flush_all)
        assert "return" in hints

    def test_set_ttl_has_return_type(self):
        hints = get_type_hints(BaseCache.set_ttl)
        assert "return" in hints

    def test_get_ttl_has_return_type(self):
        hints = get_type_hints(BaseCache.get_ttl)
        assert "return" in hints


class TestProviderPortTypeHints:
    def test_get_session_has_return_type(self):
        hints = get_type_hints(BaseProvider.get_session)
        assert "return" in hints

    def test_get_connection_has_return_type(self):
        hints = get_type_hints(BaseProvider.get_connection)
        assert "return" in hints

    def test_close_has_return_type(self):
        hints = get_type_hints(BaseProvider.close)
        assert "return" in hints

    def test_get_dao_has_return_type(self):
        hints = get_type_hints(BaseProvider.get_dao)
        assert "return" in hints

    def test_raw_has_return_type(self):
        hints = get_type_hints(BaseProvider.raw)
        assert "return" in hints

    def test_private_raw_has_return_type(self):
        hints = get_type_hints(BaseProvider._raw)
        assert "return" in hints
