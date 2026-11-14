"""Fixtures for the cache port's conformance suite.

The conformance plugin builds the domain with the adapter under test as its
default cache, and clears and closes that adapter after each test.
"""

import pytest

from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.fields import Identifier, String
from protean.infra.cache import Cache

# An expiry test writes with `SHORT_TTL`, reads the entry back, and sleeps for
# `PAST_SHORT_TTL`. The TTL is long enough that a slow Redis still holds the
# entry at the first read.
SHORT_TTL = 0.5
PAST_SHORT_TTL = 1.0


class CacheEntry(BaseProjection):
    """A projection with one `Identifier` and one `String` field.

    The suite does not test value shapes that a JSON round trip changes. For
    example, a `Dict` field with integer keys keeps them on the memory cache,
    and comes back from Redis with string keys.
    """

    key: Identifier(identifier=True)
    value: String(required=True)


@pytest.fixture
def cache(test_domain: Domain) -> Cache:
    """The `Cache` service over the adapter under test, with `CacheEntry`
    registered so `get` can rebuild its entries."""
    test_domain.register(CacheEntry)
    return test_domain.cache_for(CacheEntry)
