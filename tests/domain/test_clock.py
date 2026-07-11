"""Tests for the injectable ``domain.clock`` seam and its default clock."""

from datetime import UTC, datetime, timedelta

from protean.domain import Domain
from protean.utils import Clock, SystemClock


class TestDefaultClock:
    def test_domain_has_a_system_clock_by_default(self):
        domain = Domain(name="Clocked")
        assert isinstance(domain.clock, SystemClock)

    def test_default_clock_returns_tz_aware_utc_now(self):
        domain = Domain(name="Clocked")

        before = datetime.now(UTC)
        value = domain.clock.now()
        after = datetime.now(UTC)

        # Timezone-aware UTC, and effectively the current instant.
        assert value.tzinfo is not None
        assert value.utcoffset() == timedelta(0)
        assert before <= value <= after

    def test_default_clock_satisfies_the_clock_protocol(self):
        domain = Domain(name="Clocked")
        assert isinstance(domain.clock, Clock)


class TestClockSeam:
    def test_clock_and_system_clock_are_importable_from_public_surface(self):
        # The seam must be importable so tests and integrations can inject a
        # stub clock; these are the sanctioned public additions for issue 9.1.7.
        from protean.utils import Clock as ImportedClock
        from protean.utils import SystemClock as ImportedSystemClock

        assert ImportedClock is Clock
        assert ImportedSystemClock is SystemClock

    def test_injected_clock_replaces_the_default(self):
        domain = Domain(name="Clocked")
        frozen = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        class _Fixed:
            def now(self):
                return frozen

        domain.clock = _Fixed()
        assert domain.clock.now() == frozen

    def test_system_clock_now_matches_datetime_now(self):
        # SystemClock must be byte-for-byte equivalent to the calls it replaces,
        # so wiring the seam leaves default behavior unchanged.
        before = datetime.now(UTC)
        value = SystemClock().now()
        after = datetime.now(UTC)
        assert value.tzinfo is UTC
        assert before <= value <= after


class TestDomainNowNormalizesInjectedClock:
    """``_domain_now`` normalizes a clock reading to tz-aware UTC.

    A stub clock that returns a naive datetime (as a DB round-trip might) is
    made timezone-aware at the seam, matching how an explicit ``now`` argument is
    normalized at the call sites — so the injected-clock default is no less safe
    than the ``datetime.now(UTC)`` it replaced.
    """

    def test_naive_clock_reading_is_made_tz_aware(self, test_domain):
        from protean.utils.globals import _domain_now

        naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo

        class _NaiveClock:
            def now(self):
                return naive

        test_domain.clock = _NaiveClock()

        resolved = _domain_now()

        assert resolved.tzinfo is not None
        assert resolved.utcoffset() == timedelta(0)
        assert resolved == naive.replace(tzinfo=UTC)

    def test_explicit_naive_now_is_made_tz_aware(self):
        # An explicit ``now`` argument is normalized just like a clock reading,
        # so a caller (e.g. the outbox processor) that passes a naive value
        # never leaks it into deadline/lock comparisons or serialization.
        from protean.utils.globals import _domain_now

        naive = datetime(2026, 1, 1, 12, 0, 0)  # no tzinfo

        resolved = _domain_now(naive)

        assert resolved.tzinfo is not None
        assert resolved == naive.replace(tzinfo=UTC)

    def test_explicit_aware_now_is_returned_unchanged(self):
        from protean.utils.globals import _domain_now

        aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

        assert _domain_now(aware) == aware

    def test_falls_back_to_real_utc_without_a_domain_context(self):
        # With no active domain context, no clock is reachable, so ``_domain_now``
        # returns the real current UTC time (a plain script, or a worker before
        # bootstrap).
        from protean.utils.globals import _domain_context_stack, _domain_now

        # Suspend the autouse domain context(s) for the duration of the call.
        suspended = []
        while _domain_context_stack.top is not None:
            suspended.append(_domain_context_stack.pop())
        try:
            before = datetime.now(UTC)
            resolved = _domain_now()
            after = datetime.now(UTC)
        finally:
            for ctx in reversed(suspended):
                _domain_context_stack.push(ctx)

        assert resolved.tzinfo is not None
        assert before <= resolved <= after
