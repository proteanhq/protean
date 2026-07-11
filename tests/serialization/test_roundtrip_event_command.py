"""Events and commands: payload idempotence plus object equality
(:issue:`#1201`).

Reconstruction rebuilds volatile ``_metadata`` (fresh timestamps/versions), so
the invariant is idempotence of the *payload* (everything but ``_metadata``),
which pins that every schema field value survives the round-trip.
"""

import pytest
from hypothesis import given

from tests.serialization.strategies import (
    assert_message_roundtrip,
    cart_opened_st,
    open_cart_st,
    roundtrip_settings,
)

pytestmark = pytest.mark.no_test_domain


@roundtrip_settings
@given(cart_opened_st())
def test_event_payload_roundtrips(event):
    """Event payload (including an embedded ValueObject) round-trips."""
    assert_message_roundtrip(event)


@roundtrip_settings
@given(open_cart_st())
def test_command_payload_roundtrips(command):
    assert_message_roundtrip(command)
