"""Entities and aggregates: serializer idempotence ``S(D(S(x))) == S(x)``,
including ``HasMany`` and ``HasOne`` associations (:issue:`#1201`).

Object equality alone would be vacuous for identity-equality types (it ignores
every non-identity field), so these assert dict idempotence, which checks that
every field value — and every nested child — survives the round-trip.
"""

import pytest
from hypothesis import given

from tests.serialization.strategies import (
    assert_entity_roundtrip,
    cart_st,
    line_item_st,
    roundtrip_settings,
)

pytestmark = pytest.mark.no_test_domain


@roundtrip_settings
@given(line_item_st())
def test_entity_roundtrips(entity):
    assert_entity_roundtrip(entity)


@roundtrip_settings
@given(cart_st())
def test_aggregate_with_associations_roundtrips(aggregate):
    """An aggregate with a ValueObject, a HasMany, and a HasOne round-trips.

    The HasOne child (``Coupon``) and HasMany children (``LineItem``) are
    exercised here as part of the aggregate's round-trip.
    """
    assert_entity_roundtrip(aggregate)
