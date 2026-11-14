"""Fixtures for the cache port's conformance suite.

The conformance plugin builds the domain with the adapter under test as its
default cache, and clears and closes that adapter after each test.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.infra.cache import Cache


class CacheEntry(BaseProjection):
    """`Identifier` + `String` only.

    Narrow on purpose, but it means the memory cache's live `to_dict()`
    dict vs Redis' `json.dumps`/`json.loads` round trip is never exercised
    for value shapes where the two diverge (e.g. a `Dict` field with
    integer keys survives on memory but comes back with string keys from
    Redis' JSON round trip). Deliberately deferred, not covered here.
    """

    key: Identifier(identifier=True)
    value: String(required=True)


@pytest.fixture
def cache(test_domain: Domain) -> Cache:
    """The `Cache` service over the adapter under test, with `CacheEntry`
    registered so `get` can rebuild its entries."""
    test_domain.register(CacheEntry)
    return test_domain.cache_for(CacheEntry)
