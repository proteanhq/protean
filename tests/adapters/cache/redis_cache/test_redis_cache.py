"""Behaviour of the Redis cache adapter that the cache conformance suite does
not reach: the connection type, the JSON storage format, batched deletes,
`decode_responses` keys, `FLUSHDB` scope, the `PTTL` answer for a key with no
expiry, and the health record."""

import json
import math

import pytest
from redis import Redis

from protean.adapters.cache.redis import RedisCache
from protean.core.projection import BaseProjection
from protean.fields import Identifier, String
from tests.shared import REDIS_URI

pytestmark = pytest.mark.redis


class Token(BaseProjection):
    key: Identifier(identifier=True)
    user_id: Identifier(required=True)
    email: String(required=True)


class TestTheConnection:
    def test_the_connection_is_a_redis_client(self, test_domain):
        assert isinstance(test_domain.caches.get_connection("default"), Redis)


class TestStorageFormat:
    def test_an_entry_is_stored_as_the_json_of_the_projection_dict(self, test_domain):
        cache = test_domain.cache_for(Token)
        cache.add(Token(key="qux", user_id="foo", email="bar@baz.com"))

        raw_value = test_domain.caches.get_connection("default").get("token:::qux")

        assert json.loads(raw_value) == {
            "key": "qux",
            "user_id": "foo",
            "email": "bar@baz.com",
        }


class TestRemovalByKeyPattern:
    def test_removal_by_key_pattern_deletes_across_batches(
        self, test_domain, monkeypatch
    ):
        # Shrink the batch so the keys cross the mid-loop flush, not just the
        # final one, exercising the batched delete path end to end.
        monkeypatch.setattr(RedisCache, "_DELETE_BATCH_SIZE", 2)

        cache = test_domain.cache_for(Token)
        cache.clear()
        for i in range(5):
            cache.add(Token(key=f"batch-{i}", user_id="foo", email="bar@baz.com"))
        assert cache.count("token:::batch-*") == 5

        cache.remove_by_key_pattern("token:::batch-*")

        assert cache.count("token:::batch-*") == 0


class TestKeyPatternsWithDecodedResponses:
    def test_key_patterns_work_when_the_uri_decodes_responses(self, test_domain):
        # `from_url` passes `decode_responses` from the URI to the client, so
        # `SCAN` yields `str` keys in place of `bytes`.
        cache = RedisCache(
            "decoding", test_domain, {"URI": f"{REDIS_URI}/5?decode_responses=True"}
        )
        try:
            cache.clear()
            for key in ("token:::b", "token:::a", "other:::c"):
                cache.put(key, {"key": key}, None)

            assert cache.keys_matching("token:::*") == ["token:::a", "token:::b"]
            assert cache.count_matching("token:::*") == 2

            cache.delete_matching("token:::*")
            assert cache.keys_matching("*") == ["other:::c"]
        finally:
            cache.clear()
            cache.close()


class TestFlushing:
    def test_flushing_cache_leaves_other_databases_alone(self, test_domain):
        cache = test_domain.cache_for(Token)
        # Redis database 14 is outside every domain and adapter config in the
        # suite, so no reset or teardown flushes it while this test runs under
        # xdist. The tests that share it each use their own key.
        other_db = Redis.from_url(f"{REDIS_URI}/14")
        other_key = "protean-test:cache-flush-all-survivor"
        try:
            other_db.set(other_key, "kept")
            cache.add(Token(key="flushed", user_id="foo", email="bar@baz.com"))
            assert cache.get("token:::flushed") is not None

            cache.clear()

            assert cache.get("token:::flushed") is None
            assert other_db.get(other_key) == b"kept"
        finally:
            other_db.delete(other_key)
            other_db.close()


class TestGetTTLOnANeverExpiringKey:
    """A key written with no TTL has no expiry in Redis, which `PTTL` answers
    with `-1`. The adapter reports that as `math.inf`."""

    def test_get_ttl_of_a_never_expiring_key_is_math_inf(self, test_domain):
        adapter = test_domain.caches["default"]._adapter
        try:
            adapter.put("token:::forever", {"key": "forever"}, None)

            assert adapter.get_connection().pttl("token:::forever") == -1
            assert adapter.get_ttl("token:::forever") == math.inf
        finally:
            adapter.delete("token:::forever")


class TestHealth:
    def test_health_reports_no_pool_counters(self, test_domain):
        assert test_domain.caches["default"]._adapter.health().pool is None
