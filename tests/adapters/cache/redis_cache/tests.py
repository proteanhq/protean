import json
import time

import pytest

from redis import Redis

from protean.adapters.cache.redis import RedisCache
from protean.core.field.basic import Identifier, String
from protean.core.view import BaseView
from protean.utils import Cache


class Token(BaseView):
    key = Identifier(identifier=True)
    user_id = Identifier(required=True)
    email = String(required=True)


@pytest.mark.redis
class TestCacheInitialization:
    def test_that_a_concrete_cache_can_be_initialized_successfully(self, test_domain):
        cache = RedisCache(
            "dummy_name", test_domain, {"URI": "redis://127.0.0.1:6379/2"}
        )
        assert cache is not None

    def test_that_domain_initializes_cache_from_config(self, test_domain):
        assert len(list(test_domain.caches)) == 1
        assert isinstance(list(test_domain.caches.values())[0], RedisCache)

    def test_that_cache_can_be_retrieved(self, test_domain):
        cache_name = next(iter(test_domain.caches))
        assert cache_name is not None
        assert cache_name == "default"
        assert isinstance(test_domain.caches[cache_name], RedisCache)


@pytest.mark.redis
class TestCacheProvider:
    def test_connection(self, test_domain):
        provider = test_domain.caches.get("default")
        assert provider is not None
        assert provider.ping() is True

    def test_conn_info(self, test_domain):
        provider = test_domain.caches.get("default")
        assert provider.conn_info["CACHE"] == Cache.MEMORY.value

    def test_connection_via_provider(self, test_domain):
        provider = test_domain.caches.get("default")
        conn = provider.get_connection()
        assert conn is not None
        assert isinstance(conn, Redis)

    def test_connection_via_cache_aggregate(self, test_domain):
        conn = test_domain.caches.get_connection("default")
        assert conn is not None
        assert isinstance(conn, Redis)


@pytest.mark.redis
class TestCachePersistenceFlows:
    def test_adding_to_cache(self, test_domain):
        token = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache = test_domain.cache_for(Token)
        cache.add(token)

        value = cache.get("token:::qux")
        assert value == token

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

    def test_removal_by_view_from_cache(self, test_domain):
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
        assert 0 <= ttl / 1000 <= 300

    def test_set_ttl_on_key(self, test_domain):
        cache = test_domain.cache_for(Token)

        token1 = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token1)

        ttl = cache.get_ttl("token:::qux")
        assert 0 <= ttl / 1000 <= 300

        cache.set_ttl("token:::qux", 3000)

        ttl = cache.get_ttl("token:::qux")
        assert 2700 <= ttl / 1000 <= 3000

    def test_setting_expiry_on_add_for_key(self, test_domain):
        cache = test_domain.cache_for(Token)

        token1 = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token1, 1)

        value = cache.get("token:::qux")
        assert value is not None

        time.sleep(1)

        value = cache.get("token:::qux")
        assert value is None

    def test_flushing_cache(self, test_domain):
        cache = test_domain.cache_for(Token)

        token1 = Token(key="queen", user_id="foo", email="bar@baz.com")
        token2 = Token(key="quit", user_id="foo", email="baar@baz.com")

        cache.add(token1)
        cache.add(token2)

        total = cache.count("token:::qu*")
        assert total == 2

        cache.flush_all()

        total = cache.count("token:::qu*")
        assert total == 0


@pytest.mark.redis
class TestCacheSerialization:
    def test_serializing_view_object_data(self, test_domain):
        cache = test_domain.cache_for(Token)

        token = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token)

        provider = test_domain.caches.get("default")
        conn = provider.get_connection()
        raw_value = conn.get("token:::qux")

        assert json.loads(raw_value) == {
            "key": "qux",
            "user_id": "foo",
            "email": "bar@baz.com",
        }

    def test_deserializing_view_object_data(self, test_domain):
        cache = test_domain.cache_for(Token)

        token = Token(key="qux", user_id="foo", email="bar@baz.com")
        cache.add(token)

        value = cache.get("token:::qux")
        assert isinstance(value, Token)
        assert value == token
