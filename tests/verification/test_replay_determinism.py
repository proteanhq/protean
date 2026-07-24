"""Replay: reconstructing an event-sourced aggregate from its stream yields the
state an independent fold of that stream predicts (:issue:`#1251`).

The oracle (``expected_state``) folds the history in plain Python, *not* through
``Counter``'s ``@apply`` handlers, so a wrong handler — a dropped rename, a
mis-signed increment, an event applied out of order — is caught against a
different implementation rather than compared against itself. Both build paths
are checked against it:

* ``from_events`` — the event-sourcing reconstitution path.
* the command methods (``create`` / ``increment`` / ``rename``) — the path a
  user's code drives.

Their agreement with a common independent oracle also means the two paths agree
with each other. State is compared by the folded fields (``name``, ``value``);
``_version`` is volatile (a live-built aggregate counts uncommitted events, a
replayed one is reconstituted) and not part of the data contract.
"""

import pytest
from hypothesis import given

from tests.verification.strategies import (
    Counter,
    counter_histories,
    expected_state,
    live_build,
    property_settings,
)

pytestmark = pytest.mark.no_test_domain


@property_settings
@given(counter_histories())
def test_replay_matches_independent_oracle(events):
    replayed = Counter.from_events(events)
    expected = expected_state(events)

    assert replayed.name == expected["name"]
    assert replayed.value == expected["value"]


@property_settings
@given(counter_histories())
def test_live_build_matches_independent_oracle(events):
    live = live_build(events)
    expected = expected_state(events)

    assert live.name == expected["name"]
    assert live.value == expected["value"]


@property_settings
@given(counter_histories())
def test_reconstruction_is_a_pure_function_of_the_stream(events):
    """Two reconstructions of the same stream are identical — a guard against a
    future non-determinism (e.g. a wall-clock or random value) leaking into
    reconstructed state."""
    first = Counter.from_events(events)
    second = Counter.from_events(events)

    assert (first.name, first.value) == (second.name, second.value)
