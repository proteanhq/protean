import time

import pytest

from protean.adapters.cache.memory import MemoryCache
from protean.core.projection import BaseProjection
from protean.fields import Identifier, String
from protean.port.cache import BaseCache


class Token(BaseProjection):
    key: Identifier(identifier=True)
    user_id: Identifier(required=True)
    email: String(required=True)


class TestCacheInitialization:
    def test_that_base_repository_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseCache()

    def test_that_a_concrete_cache_can_be_initialized_successfully(self, test_domain):
        cache = MemoryCache("dummy_name", test_domain, {})
        assert cache is not None

    def test_that_domain_initializes_cache_from_config(self, test_domain):
        assert len(list(test_domain.caches)) == 1
        assert isinstance(next(iter(test_domain.caches.values())), MemoryCache)

    def test_that_cache_can_be_retrieved(self, test_domain):
        cache_name = next(iter(test_domain.caches))
        assert cache_name is not None
        assert cache_name == "default"
        assert isinstance(test_domain.caches[cache_name], MemoryCache)


class TestCacheProvider:
    def test_connection(self, test_domain):
        provider = test_domain.caches.get("default")
        assert provider is not None
        assert provider.ping() is True

    def test_conn_info(self, test_domain):
        provider = test_domain.caches.get("default")
        assert provider.conn_info["cache"] == "memory"

    def test_connection_via_provider(self, test_domain):
        provider = test_domain.caches.get("default")
        conn = provider.get_connection()
        assert conn is not None
        assert isinstance(conn, dict)

    def test_connection_via_cache_aggregate(self, test_domain):
        conn = test_domain.caches.get_connection("default")
        assert conn is not None
        assert isinstance(conn, dict)


class TestCachePersistenceFlows:
    # ADD, GET, REMOVE, EXPIRY, FLUSH_ALL
    def test_adding_to_cache(self, test_domain):
        token = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache = test_domain.cache_for(Token)
        cache.add(token)

        provider = test_domain.caches.get("default")
        conn = provider.get_connection()

        assert isinstance(conn, dict)
        assert "token:::qux" in conn
        assert conn["token:::qux"][1] == {
            "key": "qux",
            "email": "bar@baz.com",
            "user_id": "foo",
        }

    def test_fetching_from_cache(self, test_domain):
        token = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache = test_domain.cache_for(Token)
        cache.add(token)

        value = cache.get("token:::qux")
        assert value == token

    def test_get_keys_by_keyname_regex(self, test_domain):
        cache = test_domain.cache_for(Token)

        token1 = Token(key="qux", user_id="foo", email="bar@baz.com")
        token2 = Token(key="quux", user_id="fooo", email="baar@baz.com")

        cache.add(token1)
        cache.add(token2)

        tokens = cache.get_all("token:::qu*")
        assert len(tokens) == 2
        assert all(token in tokens for token in [token1, token2])

    def test_counting_keys_in_cache(self, test_domain):
        cache = test_domain.cache_for(Token)

        token1 = Token(key="qux", user_id="foo", email="bar@baz.com")
        token2 = Token(key="quux", user_id="fooo", email="baar@baz.com")

        cache.add(token1)
        cache.add(token2)

        total = cache.count("token:::qu*")
        assert total == 2

    def test_overwriting_key_in_cache(self, test_domain):
        cache = test_domain.cache_for(Token)

        token1 = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token1)

        value1 = cache.get("token:::qux")
        assert value1 == token1

        token2 = Token(key="qux", user_id="fooo", email="baar@baz.com")
        cache.add(token2)

        value2 = cache.get("token:::qux")
        assert value2 == token2

    def test_removal_by_key_from_cache(self, test_domain):
        cache = test_domain.cache_for(Token)

        token = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token)

        value = cache.get("token:::qux")
        assert value is not None

        cache.remove_by_key("token:::qux")

        value = cache.get("token:::qux")
        assert value is None

    def test_removal_by_projection_from_cache(self, test_domain):
        cache = test_domain.cache_for(Token)

        token = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token)

        value = cache.get("token:::qux")
        assert value is not None
        cache.remove(token)

        value = cache.get("token:::qux")
        assert value is None

    def test_removal_by_key_pattern_from_cache(self, test_domain):
        cache = test_domain.cache_for(Token)

        token = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token)
        value = cache.get("token:::qux")
        assert value is not None
        cache.remove_by_key_pattern("token:::qu*")

        value = cache.get("token:::qux")
        assert value is None

    def test_get_ttl_on_key(self, test_domain):
        cache = test_domain.cache_for(Token)

        token1 = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token1)

        ttl = cache.get_ttl("token:::qux")
        assert 0 <= ttl <= 300

    def test_set_ttl_on_key(self, test_domain):
        cache = test_domain.cache_for(Token)

        token1 = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token1)

        ttl = cache.get_ttl("token:::qux")
        assert 0 <= ttl <= 300

        cache.set_ttl("token:::qux", 3000)

        ttl = cache.get_ttl("token:::qux")
        assert 2700 <= ttl <= 3000

    def test_setting_expiry_on_add_for_key(self, test_domain):
        cache = test_domain.cache_for(Token)

        token1 = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token1, 0.01)

        total = cache.count("token:::qu*")
        assert total == 1

        time.sleep(0.01)

        total = cache.count("token:::qu*")
        assert total == 0

    def test_flushing_cache(self, test_domain):
        cache = test_domain.cache_for(Token)

        token1 = Token(key="qux", user_id="foo", email="bar@baz.com")
        token2 = Token(key="quux", user_id="fooo", email="baar@baz.com")

        cache.add(token1)
        cache.add(token2)

        total = cache.count("token:::qu*")
        assert total == 2

        cache.flush_all()

        total = cache.count("token:::qu*")
        assert total == 0

    def test_flush_all_keeps_backend_usable(self, test_domain):
        """The cache must stay fully usable after ``flush_all``.

        Regression: ``MemoryCache.flush_all`` reassigned ``_db`` to a plain
        ``{}``, so ``set_ttl``/``get_ttl`` (used by ``add(..., ttl=...)``)
        raised ``AttributeError`` on the next operation.
        """
        cache = test_domain.cache_for(Token)
        cache.add(Token(key="qux", user_id="foo", email="bar@baz.com"))

        cache.flush_all()

        # add-with-ttl exercises set_ttl; must not raise after a flush.
        cache.add(Token(key="quux", user_id="foo", email="bar@baz.com"), ttl=100)
        assert cache.count("token:::qu*") == 1


class TestCacheSerialization:
    def test_serializing_projection_object_data(self, test_domain):
        cache = test_domain.cache_for(Token)

        token = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token)

        provider = test_domain.caches.get("default")
        conn = provider.get_connection()
        raw_value = conn["token:::qux"]

        assert raw_value[1] == {"key": "qux", "user_id": "foo", "email": "bar@baz.com"}

    def test_deserializing_projection_object_data(self, test_domain):
        cache = test_domain.cache_for(Token)

        token = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token)

        value = cache.get("token:::qux")
        assert isinstance(value, Token)
        assert value == token


class TestAddWithAnExplicitTTL:
    """`add(..., ttl=...)` used to be read with `if ttl:`, so `0` was ignored."""

    def _token(self):
        return Token(key="tok-1", user_id="u-1", email="a@example.com")

    def test_an_explicit_ttl_is_applied_to_the_key(self, test_domain):
        cache = test_domain.caches["default"]
        cache.add(self._token(), ttl=45)

        assert cache.get_ttl("token:::tok-1") == pytest.approx(45, abs=1)

    def test_a_string_ttl_is_coerced(self, test_domain):
        """A caller reading a TTL out of config gets a string, same as `TTL=`."""
        cache = test_domain.caches["default"]
        cache.add(self._token(), ttl="45")

        assert cache.get_ttl("token:::tok-1") == pytest.approx(45, abs=1)

    def test_omitting_the_ttl_uses_the_cache_default(self, test_domain):
        cache = test_domain.caches["default"]
        cache.add(self._token())

        assert cache.get_ttl("token:::tok-1") == pytest.approx(cache.ttl, abs=1)

    def test_a_zero_ttl_is_rejected_not_silently_replaced(self, test_domain):
        """It used to fall through to the default, caching for 5 minutes."""
        from protean.exceptions import ConfigurationError

        cache = test_domain.caches["default"]
        with pytest.raises(ConfigurationError, match="positive"):
            cache.add(self._token(), ttl=0)


class TestSetTTLTakesTheSameShapesAsAdd:
    """`set_ttl` had the string bug that `add` had, one method along.

    Both are public and both take a TTL, so a value that works in one has to
    work in the other. `set_ttl(key, "45")` used to raise
    `TypeError: unsupported operand type(s) for +: 'float' and 'str'` from
    inside the TTL bookkeeping, nowhere near the call.
    """

    def _stored(self, test_domain):
        cache = test_domain.caches["default"]
        cache.add(Token(key="tok-2", user_id="u-1", email="a@example.com"))
        return cache, "token:::tok-2"

    def test_a_numeric_ttl_works(self, test_domain):
        cache, key = self._stored(test_domain)
        cache.set_ttl(key, 45)
        assert cache.get_ttl(key) == pytest.approx(45, abs=1)

    def test_a_string_ttl_works_too(self, test_domain):
        cache, key = self._stored(test_domain)
        cache.set_ttl(key, "45")
        assert cache.get_ttl(key) == pytest.approx(45, abs=1)

    @pytest.mark.parametrize("bad", [0, -5, "nan", "inf", "later"])
    def test_a_bad_ttl_is_rejected_the_same_way_as_in_add(self, test_domain, bad):
        from protean.exceptions import ConfigurationError

        cache, key = self._stored(test_domain)
        with pytest.raises(ConfigurationError):
            cache.set_ttl(key, bad)
