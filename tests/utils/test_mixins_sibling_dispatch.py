"""Sibling handler methods are independent reactions and must not cancel each other.

An event handler or projector can register several methods for one event. Each
runs in its own ``UnitOfWork``, so they are already transactionally independent.
They used to share a fate anyway: ``_dispatch_handlers`` let the first exception
propagate, so the remaining methods never ran, and since ``_handlers`` is a
``set`` the skipped ones were arbitrary.

Tests that dispatch through ``_handle`` assert order-independently, because the
registry is a ``set`` and the order is deliberately unspecified (ADR-0031). A few
call ``_dispatch_handlers`` with an explicit list so they can pin what runs after
a failure; each of those says why in its own docstring.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.exceptions import ExpectedVersionError
from protean.fields import Identifier, String
from protean.utils.mixins import handle

ran: list[str] = []


class OneFailed(Exception):
    """Raised by a sibling that fails."""


class AnotherFailed(Exception):
    """Raised by a second failing sibling, to keep the two distinguishable."""


class Order(BaseAggregate):
    name: String()


class Placed(BaseEvent):
    order_id: Identifier()


class OneSiblingFails(BaseEventHandler):
    @handle(Placed)
    def alpha(self, event: Placed) -> None:
        ran.append("alpha")

    @handle(Placed)
    def beta(self, event: Placed) -> None:
        ran.append("beta")
        raise OneFailed("beta could not do its part")

    @handle(Placed)
    def gamma(self, event: Placed) -> None:
        ran.append("gamma")


class TwoSiblingsFail(BaseEventHandler):
    @handle(Placed)
    def alpha(self, event: Placed) -> None:
        ran.append("alpha")
        raise OneFailed("alpha could not do its part")

    @handle(Placed)
    def beta(self, event: Placed) -> None:
        ran.append("beta")
        raise AnotherFailed("beta could not do its part either")

    @handle(Placed)
    def gamma(self, event: Placed) -> None:
        ran.append("gamma")


class NoSiblingFails(BaseEventHandler):
    @handle(Placed)
    def alpha(self, event: Placed) -> None:
        ran.append("alpha")

    @handle(Placed)
    def beta(self, event: Placed) -> None:
        ran.append("beta")


class SiblingRaisesBaseException(BaseEventHandler):
    @handle(Placed)
    def alpha(self, event: Placed) -> None:
        ran.append("alpha")
        raise KeyboardInterrupt("operator stopped the process")

    @handle(Placed)
    def beta(self, event: Placed) -> None:
        ran.append("beta")


class TwoSiblingsConflict(BaseEventHandler):
    @handle(Placed)
    def alpha(self, event: Placed) -> None:
        ran.append("alpha")
        raise ExpectedVersionError("alpha lost the race")

    @handle(Placed)
    def beta(self, event: Placed) -> None:
        ran.append("beta")
        raise ExpectedVersionError("beta lost the race")


class MixedFailures(BaseEventHandler):
    @handle(Placed)
    def plain(self, event: Placed) -> None:
        ran.append("plain")
        raise OneFailed("plain could not do its part")

    @handle(Placed)
    def conflicting(self, event: Placed) -> None:
        ran.append("conflicting")
        raise ExpectedVersionError("conflicting lost the race")


class MixedInterrupt(BaseEventHandler):
    @handle(Placed)
    def plain(self, event: Placed) -> None:
        ran.append("plain")
        raise OneFailed("plain could not do its part")

    @handle(Placed)
    def interrupting(self, event: Placed) -> None:
        ran.append("interrupting")
        raise KeyboardInterrupt("operator stopped the process")


class Unprintable(Exception):
    """A failure whose ``__str__`` blows up, like a detached ORM row."""

    def __str__(self) -> str:
        raise RuntimeError("str exploded")


class UnprintableThenInterrupt(BaseEventHandler):
    @handle(Placed)
    def unprintable(self, event: Placed) -> None:
        ran.append("unprintable")
        raise Unprintable()

    @handle(Placed)
    def interrupting(self, event: Placed) -> None:
        ran.append("interrupting")
        raise KeyboardInterrupt("operator stopped the process")


class OrderSummary(BaseProjection):
    order_id: Identifier(identifier=True)
    name: String()


class SummaryProjector(BaseProjector):
    @handle(Placed)
    def alpha(self, event: Placed) -> None:
        ran.append("alpha")
        raise OneFailed("alpha could not do its part")

    @handle(Placed)
    def beta(self, event: Placed) -> None:
        ran.append("beta")


@pytest.fixture(autouse=True)
def registered_domain(test_domain):
    """Register the elements and give every test a clean ``ran`` log."""
    ran.clear()
    test_domain.register(Order)
    test_domain.register(Placed, part_of=Order)
    test_domain.register(OneSiblingFails, part_of=Order)
    test_domain.register(TwoSiblingsFail, part_of=Order)
    test_domain.register(NoSiblingFails, part_of=Order)
    test_domain.register(SiblingRaisesBaseException, part_of=Order)
    test_domain.register(TwoSiblingsConflict, part_of=Order)
    test_domain.register(MixedFailures, part_of=Order)
    test_domain.register(MixedInterrupt, part_of=Order)
    test_domain.register(UnprintableThenInterrupt, part_of=Order)
    test_domain.register(OrderSummary)
    test_domain.register(
        SummaryProjector, projector_for=OrderSummary, aggregates=[Order]
    )
    test_domain.init(traverse=False)
    return test_domain


class TestSiblingsAllRun:
    def test_a_failing_method_does_not_skip_the_ones_after_it(self):
        """Dispatch order is pinned here on purpose.

        Going through ``_handle`` would read ``_handlers``, which is a ``set``,
        so the failing method could land last and every sibling would run
        anyway. Handing ``_dispatch_handlers`` an ordered sequence with the
        failure first means a dispatcher that stops on the first exception can
        never reach the ones after it.
        """
        ordered = [OneSiblingFails.beta, OneSiblingFails.alpha, OneSiblingFails.gamma]

        with pytest.raises(OneFailed):
            OneSiblingFails._dispatch_handlers(ordered, Placed(order_id="1"))

        assert ran == ["beta", "alpha", "gamma"]

    def test_siblings_run_when_two_fail(self):
        with pytest.raises(ExceptionGroup):
            TwoSiblingsFail._handle(Placed(order_id="1"))

        assert sorted(ran) == ["alpha", "beta", "gamma"]

    def test_nothing_is_raised_when_every_sibling_succeeds(self):
        NoSiblingFails._handle(Placed(order_id="1"))

        assert sorted(ran) == ["alpha", "beta"]

    def test_a_projector_isolates_its_siblings_too(self):
        """Order pinned for the same reason as the event-handler case: through
        ``_handle`` the failing method lands first only about half the time, so
        the scenario itself, not just the assertion, has to be deterministic."""
        ordered = [SummaryProjector.alpha, SummaryProjector.beta]

        with pytest.raises(OneFailed):
            SummaryProjector._dispatch_handlers(ordered, Placed(order_id="1"))

        assert ran == ["alpha", "beta"]


class TestHowFailuresSurface:
    def test_a_single_failure_propagates_unchanged(self):
        """The exception type is preserved, so a ``handle_error`` override that
        matches on it keeps working, and so does the engine's ``except``."""
        with pytest.raises(OneFailed) as exc_info:
            OneSiblingFails._handle(Placed(order_id="1"))

        assert str(exc_info.value) == "beta could not do its part"

    def test_several_failures_are_raised_together(self):
        with pytest.raises(ExceptionGroup) as exc_info:
            TwoSiblingsFail._handle(Placed(order_id="1"))

        group = exc_info.value
        assert len(group.exceptions) == 2
        assert {type(exc) for exc in group.exceptions} == {OneFailed, AnotherFailed}
        assert {str(exc) for exc in group.exceptions} == {
            "alpha could not do its part",
            "beta could not do its part either",
        }
        # The message has to name the handler and the event, because the group
        # is what an operator sees in the engine's failure log.
        assert "TwoSiblingsFail" in str(group)
        assert "Placed" in str(group)
        assert "2 handler methods failed" in str(group)


class TestVersionConflictsAreNotCollected:
    """A version conflict has to keep its own type all the way out.

    ``UnitOfWork.commit`` classifies by exception type, and the version-retry
    loop in ``@handle`` matches on ``ExpectedVersionError``. Neither matches an
    ``ExceptionGroup``, so collecting a conflict alongside another failure would
    surface it as a ``TransactionError`` and the retry that resolves it would
    stop firing.
    """

    def test_a_conflict_is_not_grouped_with_another_conflict(self):
        with pytest.raises(ExpectedVersionError) as exc_info:
            TwoSiblingsConflict._handle(Placed(order_id="1"))

        assert not isinstance(exc_info.value, ExceptionGroup)

    def test_a_conflict_propagates_past_an_already_collected_failure(self):
        ordered = [MixedFailures.plain, MixedFailures.conflicting]

        with pytest.raises(ExpectedVersionError) as exc_info:
            MixedFailures._dispatch_handlers(ordered, Placed(order_id="1"))

        # The collected failure must travel with the conflict; this path skips
        # `handle_error` the same way the interrupt path does.
        notes = getattr(exc_info.value, "__notes__", [])
        assert notes and "plain could not do its part" in notes[0]

        # The plain failure ran first and was collected; the conflict still
        # comes out as itself instead of being bundled with it. `conflicting`
        # appears more than once because the version-retry loop inside
        # ``@handle`` re-runs that method before giving up.
        assert ran[0] == "plain"
        assert set(ran) == {"plain", "conflicting"}


class TestBaseExceptionsStopDispatch:
    def test_a_base_exception_stops_dispatch_instead_of_being_collected(self):
        """Order is pinned so this can actually fail.

        Going through ``_handle`` would prove nothing: a lone collected
        ``KeyboardInterrupt`` is re-raised by the single-failure path, so
        widening the ``except`` to ``BaseException`` would still satisfy
        ``pytest.raises``. Putting the raising method first and asserting the
        second never ran is what pins "dispatch stopped".
        """
        ordered = [
            SiblingRaisesBaseException.alpha,
            SiblingRaisesBaseException.beta,
        ]

        with pytest.raises(KeyboardInterrupt):
            SiblingRaisesBaseException._dispatch_handlers(ordered, Placed(order_id="1"))

        assert ran == ["alpha"]

    def test_failures_collected_before_it_are_not_lost(self):
        """The engine catches ``Exception``, so on this path ``handle_error``
        never runs. Anything already collected has to travel with the
        interrupt or nothing reports it at all."""
        ordered = [MixedInterrupt.plain, MixedInterrupt.interrupting]

        with pytest.raises(KeyboardInterrupt) as exc_info:
            MixedInterrupt._dispatch_handlers(ordered, Placed(order_id="1"))

        notes = getattr(exc_info.value, "__notes__", [])
        assert notes, "the discarded failure left no trace on the interrupt"
        assert "plain could not do its part" in notes[0]
        assert "MixedInterrupt" in notes[0]

    def test_an_unprintable_failure_does_not_replace_the_interrupt(self):
        """Annotating is best-effort. A collected failure whose ``__str__``
        raises must not become the exception that leaves dispatch, or an
        interrupt gets swallowed and the engine keeps running."""
        ordered = [
            UnprintableThenInterrupt.unprintable,
            UnprintableThenInterrupt.interrupting,
        ]

        with pytest.raises(KeyboardInterrupt):
            UnprintableThenInterrupt._dispatch_handlers(ordered, Placed(order_id="1"))
