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
