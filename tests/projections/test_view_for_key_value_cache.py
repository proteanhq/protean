"""`view_for` on a projection whose cache supports only key-value calls.

`get` builds one key and needs no capability. `count` reads every entry of the
projection by pattern, so it needs `CacheCapabilities.PATTERN_MATCH`.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.exceptions import NotSupportedError, ObjectNotFoundError
from protean.fields import Identifier, String
from protean.infra.registry import caches as cache_registry
from tests.cache.test_cache_service import KeyValueCache


class Contact(BaseProjection):
    contact_id: Identifier(identifier=True)
    name: String(required=True)


@pytest.fixture(autouse=True)
def key_value_cache(test_domain):
    cache_registry.register(
        "key_value_only", f"{KeyValueCache.__module__}.{KeyValueCache.__qualname__}"
    )
    try:
        test_domain.config["caches"]["plain"] = {"provider": "key_value_only"}
        test_domain.register(Contact, cache="plain")
        test_domain.init(traverse=False)
        yield
    finally:
        cache_registry._paths.pop("key_value_only", None)


class TestAKeyValueOnlyCacheBehindAReadView:
    def test_get_returns_the_cached_projection(self, test_domain):
        test_domain.cache_for(Contact).add(Contact(contact_id="1", name="Ada"))

        contact = test_domain.view_for(Contact).get("1")

        assert (contact.contact_id, contact.name) == ("1", "Ada")

    def test_get_of_a_missing_identifier_is_not_found(self, test_domain):
        with pytest.raises(ObjectNotFoundError):
            test_domain.view_for(Contact).get("missing")

    def test_count_needs_pattern_match(self, test_domain):
        test_domain.cache_for(Contact).add(Contact(contact_id="1", name="Ada"))

        with pytest.raises(NotSupportedError) as exc:
            test_domain.view_for(Contact).count()

        assert "Cache 'plain'" in str(exc.value)
        assert "CacheCapabilities.PATTERN_MATCH" in str(exc.value)
