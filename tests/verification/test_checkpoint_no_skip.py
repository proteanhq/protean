"""Checkpoint never skips a committed event, machine-checked over randomized
commit interleavings (:issue:`#1251`).

``global_position`` is assigned in order but committed possibly out of order
across categories, so a lower position can become visible after a higher one. A
``$all`` subscription must never advance its checkpoint past a position that has
not yet committed — otherwise that position, once it commits, is skipped.

This is a Hypothesis ``RuleBasedStateMachine``. It models the store as two sets —
``committed`` (visible) and ``pending`` (assigned, not yet committed, i.e. a live
gap) — and drives the real ``EventStoreSubscription._gap_safe_batch`` plus the
cursor advancement its ``tick`` performs. ``gap_timeout_seconds`` is set
effectively infinite so a gap is only ever resolved by committing, never
abandoned — that isolates the pure no-skip guarantee (timeout-based abandonment
of rolled-back positions is covered by the unit tests in
``tests/subscription/test_all_gap_safety.py``).

Two invariants hold after every step:

* **No skip** — while any position is pending, the cursor stays strictly below
  the lowest pending one.
* **Delivered contiguity** — every committed position at or below the cursor has
  been delivered; nothing below the cursor was skipped.
"""

import pytest
from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from tests.verification.strategies import (
    build_all_subscription,
    message_at,
    verification_domain,
)

pytestmark = pytest.mark.no_test_domain

_INFINITE_TIMEOUT = 10**9

# One subscription instance, reset per example — avoids rebuilding the engine for
# every Hypothesis run. ``_gap_safe_batch`` is pure, so reuse-after-reset is safe.
_subscription = build_all_subscription()


class CheckpointNoSkip(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.sub = _subscription
        self.sub.current_position = -1
        self.sub.messages_since_last_position_write = 0
        self.sub._gap_first_seen = {}
        self.sub._gap_watermark = -1
        self.sub.gap_timeout_seconds = _INFINITE_TIMEOUT

        self.next_position = 1
        self.pending: set[int] = set()
        self.committed: list[int] = []
        self.delivered: set[int] = set()

    @rule()
    def commit_in_order(self):
        """Assign the next position and commit it immediately."""
        self.committed.append(self.next_position)
        self.next_position += 1

    @rule()
    def assign_gap(self):
        """Assign the next position but hold it uncommitted — a live gap."""
        self.pending.add(self.next_position)
        self.next_position += 1

    @rule(data=st.data())
    @precondition(lambda self: bool(self.pending))
    def commit_pending(self, data):
        """Commit a held position out of order — the position becomes visible
        after ones assigned later already have."""
        position = data.draw(st.sampled_from(sorted(self.pending)))
        self.pending.discard(position)
        self.committed.append(position)

    @rule()
    def tick(self):
        """One subscription read: feed the visible positions above the cursor to
        ``_gap_safe_batch`` and advance the cursor exactly as ``tick`` does."""
        visible = sorted(p for p in self.committed if p > self.sub.current_position)
        returned = self.sub._gap_safe_batch([message_at(p) for p in visible])
        for message in returned:
            position = message.metadata.event_store.global_position
            self.sub.current_position = position
            self.delivered.add(position)
        # Mirrors ``tick``'s post-processing step past abandoned holes. Under the
        # infinite gap timeout no hole is ever abandoned, so the watermark never
        # outruns the delivered frontier here — abandonment is covered by
        # ``tests/subscription/test_all_gap_safety.py``.
        if self.sub._gap_watermark > self.sub.current_position:  # pragma: no cover
            self.sub.current_position = self.sub._gap_watermark

        # Progress: a gap-free drain must reach the committed frontier in one
        # tick. Guards against a regression where the batch stops yielding and
        # the safety invariants pass vacuously (cursor frozen, nothing delivered).
        if self.committed and not self.pending:
            assert self.sub.current_position == max(self.committed), (
                f"cursor {self.sub.current_position} did not drain to the "
                f"committed frontier {max(self.committed)} with no open gaps"
            )

    @invariant()
    def cursor_never_passes_a_pending_position(self):
        if self.pending:
            assert self.sub.current_position < min(self.pending), (
                f"cursor {self.sub.current_position} advanced past a pending "
                f"position; pending={sorted(self.pending)}"
            )

    @invariant()
    def every_committed_position_below_cursor_is_delivered(self):
        due = {p for p in self.committed if p <= self.sub.current_position}
        assert due <= self.delivered, (
            f"committed positions {sorted(due - self.delivered)} at or below "
            f"cursor {self.sub.current_position} were never delivered"
        )


CheckpointNoSkip.TestCase.settings = hypothesis_settings(
    max_examples=200,
    deadline=None,
    stateful_step_count=40,
    suppress_health_check=[HealthCheck.too_slow],
)
TestCheckpointNoSkip = CheckpointNoSkip.TestCase


def test_no_gaps_delivers_every_committed_position():
    """Liveness sanity check outside the state machine: with no gaps, ticking
    drains every committed position in order (guards against a vacuous no-skip
    invariant satisfied by a subscription that delivers nothing)."""
    with verification_domain.domain_context():
        sub = build_all_subscription()
        sub.current_position = -1
        sub._gap_first_seen = {}
        sub._gap_watermark = -1

        committed = list(range(1, 8))
        returned = sub._gap_safe_batch([message_at(p) for p in committed])
        delivered = [m.metadata.event_store.global_position for m in returned]

        assert delivered == committed
