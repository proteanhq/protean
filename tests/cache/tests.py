import pytest

from protean.port.cache import BaseCache
from protean.adapters.cache.memory import MemoryCache
from protean.utils import Cache


class TestCacheInitialization:
    def test_that_base_repository_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseCache()

    @pytest.mark.skip
    def test_that_a_concrete_cache_can_be_initialized_successfully(self, test_domain):
        broker = MemoryCache("dummy_name", test_domain, {})
        assert broker is not None

    @pytest.mark.skip
    def test_that_domain_initializes_cache_from_config(self, test_domain):
        assert len(list(test_domain.caches)) == 1
        assert isinstance(list(test_domain.caches.values())[0], MemoryCache)

    @pytest.mark.skip
    def test_that_cache_can_be_retrieved(self, test_domain):
        cache = test_domain.get_cache()
        assert cache is not None
        assert isinstance(cache, MemoryCache)


class TestCacheProvider:
    def test_connection(test_domain):
        provider = test_domain.get_cache_provider()
        assert provider is not None
        assert provider.ping() is True

    def test_conn_info(test_domain):
        provider = test_domain.get_cache_provider()
        assert provider.conn_info["CACHE"] == Cache.MEMORY.value

    def test_connection(test_domain):
        provider = test_domain.get_cache_provider()
        conn = provider.get_connection()
        assert conn is not None
        assert isinstance(conn, MemoryConnection)


class TestCachePersistenceFlows:
    # ADD, GET, REMOVE, EXPIRY, FLUSH_ALL
    @pytest.mark.skip
    def test_adding_to_cache(test_domain):
        token = Token(identifier="qux", user_id="foo", email="bar@baz.com")
        cache = test_domain.cache_for(Token)
        cache.add(token)

        provider = test_domain.get_cache_provider()
        conn = provider.get_connection()
        assert "token-qux" in conn
        assert conn["token-qux"] == {"user_id": "foo", "email": "bar@baz.com"}

    @pytest.mark.skip
    def test_fetching_from_cache():
        token = Token(identifier="qux", user_id="foo", email="bar@baz.com")
        cache = test_domain.cache_for(Token)
        cache.add(token)

        value = cache.get("token-qux")
        assert value == token

    @pytest.mark.skip
    def test_get_keys_by_keyname_regex():
        cache = test_domain.cache_for(Token)

        token1 = Token(identifier="qux", user_id="foo", email="bar@baz.com")
        token1 = Token(identifier="quux", user_id="fooo", email="baar@baz.com")

        cache.add(token1)
        cache.add(token2)

        values = cache.get_all("token-qu*")
        assert len(values) == 2
        assert all(key in values for key in ["qux", "quux"])

    @pytest.mark.skip
    def test_counting_keys_in_cache():
        cache = test_domain.cache_for(Token)

        token1 = Token(identifier="qux", user_id="foo", email="bar@baz.com")
        token1 = Token(identifier="quux", user_id="fooo", email="baar@baz.com")

        cache.add(token1)
        cache.add(token2)

        total = cache.count("token-qu*")
        assert total == 2

    @pytest.mark.skip
    def test_overwriting_key_in_cache():
        cache = test_domain.cache_for(Token)

        token1 = Token(identifier="qux", user_id="foo", email="bar@baz.com")
        cache.add(token1)

        value1 = cache.get("token-qux")
        assert value1 == token1

        token2 = Token(identifier="qux", user_id="fooo", email="baar@baz.com")
        cache.add(token2)

        value2 = cache.get("token-qux")
        assert value2 == token2

    @pytest.mark.skip
    def test_removing_from_cache():
        cache = test_domain.cache_for(Token)

        token = Token(identifier="qux", user_id="foo", email="bar@baz.com")
        cache.add(token)

        value = cache.get("token-qux")
        assert value is not None

        cache.remove("token-qux")

        value = cache.get("token-qux")
        assert value is None

    @pytest.mark.skip
    def test_setting_expiry_for_key():
        pass

    @pytest.mark.skip
    def test_flushing_cache():
        cache = test_domain.cache_for(Token)

        token1 = Token(identifier="qux", user_id="foo", email="bar@baz.com")
        token1 = Token(identifier="quux", user_id="fooo", email="baar@baz.com")

        cache.add(token1)
        cache.add(token2)

        total = cache.count("token-qu*")
        assert total == 2

        cache.flush_all()

        total = cache.count("token-qu*")
        assert total == 0


class TestCacheSerialization:
    @pytest.mark.skip
    def test_serializing_view_object_data(test_domain):
        cache = test_domain.cache_for(Token)

        token = Token(identifier="qux", user_id="foo", email="bar@baz.com")
        cache.add(token)

        provider = test_domain.get_cache_provider()
        conn = provider.get_connection()
        raw_value = conn["token-qux"]

        assert raw_value == {"user_id": "foo", "email": "bar@baz.com"}

    @pytest.mark.skip
    def test_deserializing_view_object_data():
        cache = test_domain.cache_for(Token)

        token = Token(identifier="qux", user_id="foo", email="bar@baz.com")
        cache.add(token)

        value = cache.get("token-qux")
        assert isinstance(value, Token)
        assert value == token
