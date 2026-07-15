"""Value objects: ``D(S(x)) == x`` across every scalar/collection field type
and nested value objects (:issue:`#1201`)."""

import pytest
from hypothesis import given

from tests.serialization.strategies import (
    address_st,
    assert_value_object_roundtrip,
    money_st,
    roundtrip_settings,
    scalars_st,
)

pytestmark = pytest.mark.no_test_domain


@roundtrip_settings
@given(scalars_st())
def test_scalars_value_object_roundtrips(vo):
    """Every scalar/collection field type survives S then D unchanged."""
    assert_value_object_roundtrip(vo)


@roundtrip_settings
@given(money_st())
def test_money_value_object_roundtrips(vo):
    assert_value_object_roundtrip(vo)


@roundtrip_settings
@given(address_st())
def test_nested_value_object_roundtrips(vo):
    """A ValueObject embedded inside a ValueObject round-trips recursively."""
    assert_value_object_roundtrip(vo)
