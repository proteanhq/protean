"""Boundary tests for ``_deadline_exceeded_after`` under an injected clock.

The retry loop stops instead of sleeping into an attempt that would start
already past the in-context command's deadline. ``_deadline_exceeded_after``
reads the active domain's clock for "now", so a frozen clock makes the
"would the next attempt start after the deadline?" decision deterministic —
including the exact-instant boundary that no wall-clock test can reach.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from protean.utils.eventing import MessageHeaders
from protean.utils.globals import g
from protean.utils.mixins import _deadline_exceeded_after
from tests.shared import FrozenClock

T0 = datetime(2030, 6, 1, 12, 0, 0, tzinfo=UTC)
# A deadline in the real past: with a bare ``datetime.now()`` the wall clock is
# already well beyond it, so freezing the clock *before* it is the only way the
# "not exceeded" verdict can hold. That divergence is what pins the seam.
PAST = datetime(2020, 6, 1, 12, 0, 0, tzinfo=UTC)


def _set_in_context_message(deadline):
    """Install a minimal in-context message carrying ``deadline`` on ``g``."""
    headers = MessageHeaders(deadline=deadline)
    g.message_in_context = SimpleNamespace(metadata=SimpleNamespace(headers=headers))


@pytest.fixture
def frozen_domain(test_domain):
    """A domain whose clock is frozen at ``T0``."""
    test_domain.clock = FrozenClock(T0)
    yield test_domain
    g.pop("message_in_context", None)


class TestDeadlineExceededAfterBoundary:
    def test_next_attempt_before_deadline_is_not_exceeded(self, frozen_domain):
        _set_in_context_message(T0 + timedelta(seconds=10))
        # now (T0) + 9s = T0+9 < T0+10 deadline -> would start in time.
        assert _deadline_exceeded_after(9) is False

    def test_next_attempt_past_deadline_is_exceeded(self, frozen_domain):
        _set_in_context_message(T0 + timedelta(seconds=10))
        # now (T0) + 11s = T0+11 > T0+10 deadline -> would start expired.
        assert _deadline_exceeded_after(11) is True

    def test_next_attempt_at_exact_deadline_is_not_exceeded(self, frozen_domain):
        _set_in_context_message(T0 + timedelta(seconds=10))
        # now (T0) + 10s == deadline exactly; expiry is strict `>`, so an
        # attempt starting exactly at the deadline is still in time.
        assert _deadline_exceeded_after(10) is False


class TestDeadlineExceededAfterSeamDivergence:
    """Cases where the frozen-clock and wall-clock verdicts disagree.

    ``T0`` sits in the future, so the boundary tests above hold under a bare
    ``datetime.now()`` too — they guard the ``>`` operator but not that the
    injected clock is actually read. Here the deadline is in the real past with
    the clock frozen just before it: the "not exceeded" result is true *only*
    under the frozen clock (real-now is long past the deadline). Dropping the
    ``_domain_now()`` read therefore flips these to "exceeded", so they guard the
    seam itself.
    """

    @pytest.fixture
    def frozen_past_domain(self, test_domain):
        test_domain.clock = FrozenClock(PAST)
        yield test_domain
        g.pop("message_in_context", None)

    def test_before_past_deadline_is_not_exceeded_only_under_clock(
        self, frozen_past_domain
    ):
        _set_in_context_message(PAST + timedelta(seconds=10))
        # Frozen now (PAST) + 9s < PAST+10 deadline -> not exceeded. A wall clock
        # (years later) would report exceeded, so this only passes via the clock.
        assert _deadline_exceeded_after(9) is False

    def test_at_exact_past_deadline_is_not_exceeded_only_under_clock(
        self, frozen_past_domain
    ):
        _set_in_context_message(PAST + timedelta(seconds=10))
        # Frozen now (PAST) + 10s == deadline exactly; strict `>` keeps it in
        # time. Wall-clock now is far past the deadline, so the exact-instant
        # verdict is reachable only through the injected clock.
        assert _deadline_exceeded_after(10) is False


class TestDeadlineExceededAfterFallbacks:
    def test_no_in_context_message_is_unconstrained(self, frozen_domain):
        # No message in context -> nothing to honor -> never constrained.
        g.pop("message_in_context", None)
        assert _deadline_exceeded_after(9999) is False

    def test_message_without_deadline_is_unconstrained(self, frozen_domain):
        # A message whose command carries no deadline is never constrained.
        _set_in_context_message(None)
        assert _deadline_exceeded_after(9999) is False

    @pytest.mark.no_test_domain
    def test_no_active_domain_context_is_unconstrained(self):
        # With no domain context at all, reading the message context raises and
        # the retry path is left unconstrained rather than propagating.
        assert _deadline_exceeded_after(9999) is False
