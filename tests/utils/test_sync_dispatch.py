"""Unit tests for the breadth-first synchronous dispatch helper (ADR-0016)."""

import logging

import pytest

from protean.exceptions import ExpectedVersionError
from protean.utils.globals import g
from protean.utils.sync_dispatch import (
    _carry_discarded_failures,
    dispatch_events_sync,
    drain_sync_dispatch,
    enqueue_sync_dispatch,
)


def test_drain_processes_enqueued_pairs_in_fifo_order(test_domain):
    with test_domain.domain_context():
        seen = []

        class Handler:
            @classmethod
            def _handle(cls, event):
                seen.append(event)

        enqueue_sync_dispatch("a", Handler)
        enqueue_sync_dispatch("b", Handler)
        drain_sync_dispatch()

        assert seen == ["a", "b"]
        # A clean drain leaves no residual chain state.
        assert getattr(g, "_sync_dispatch_queue", None) is None
        assert getattr(g, "_sync_dispatch_draining", False) is False


def test_nested_drain_is_a_noop_outer_drain_runs_everything(test_domain):
    """A handler that enqueues and asks to drain does NOT run the new event
    re-entrantly; the outermost drain picks it up after the handler returns."""
    with test_domain.domain_context():
        order = []

        class Inner:
            @classmethod
            def _handle(cls, event):
                order.append(("inner", event))

        class Outer:
            @classmethod
            def _handle(cls, event):
                order.append(("outer-start", event))
                enqueue_sync_dispatch("nested", Inner)
                drain_sync_dispatch()  # nested → must be a no-op
                order.append(("outer-end", event))

        enqueue_sync_dispatch("first", Outer)
        drain_sync_dispatch()

        # Inner runs only AFTER Outer fully returns — breadth-first, not nested.
        assert order == [
            ("outer-start", "first"),
            ("outer-end", "first"),
            ("inner", "nested"),
        ]


def test_captures_and_restores_message_in_context(test_domain):
    with test_domain.domain_context():
        g.message_in_context = "root"
        seen = []

        class Handler:
            @classmethod
            def _handle(cls, event):
                seen.append(g.get("message_in_context"))

        enqueue_sync_dispatch("e", Handler)
        drain_sync_dispatch()

        # The handler saw the context captured at enqueue time...
        assert seen == ["root"]
        # ...and the caller's context is intact afterwards.
        assert g.get("message_in_context") == "root"


def test_message_in_context_restored_after_handler_error(test_domain):
    """A handler raising mid-drain must not corrupt the caller's context."""
    with test_domain.domain_context():
        g.message_in_context = "root"

        class Boom:
            @classmethod
            def _handle(cls, event):
                raise RuntimeError("boom")

        enqueue_sync_dispatch("e", Boom)
        with pytest.raises(RuntimeError, match="boom"):
            drain_sync_dispatch()

        assert g.get("message_in_context") == "root"


def test_queue_and_flag_cleared_after_error(test_domain):
    with test_domain.domain_context():

        class Boom:
            @classmethod
            def _handle(cls, event):
                raise RuntimeError("boom")

        enqueue_sync_dispatch("x", Boom)
        with pytest.raises(RuntimeError, match="boom"):
            drain_sync_dispatch()

        # Later work starts from a clean slate.
        assert getattr(g, "_sync_dispatch_queue", None) is None
        assert getattr(g, "_sync_dispatch_draining", False) is False


def test_dispatch_events_sync_fans_out_every_pair_and_drains(test_domain):
    """The public entry point enqueues one (event, handler) pair per handler that
    ``handlers_for`` resolves, then drains once. So a caller never enqueues or
    drains by hand: every handler runs, event by event and in handler order, and
    a single drain leaves no residual chain state."""
    with test_domain.domain_context():
        seen = []

        class H1:
            @classmethod
            def _handle(cls, event):
                seen.append(("h1", event))

        class H2:
            @classmethod
            def _handle(cls, event):
                seen.append(("h2", event))

        handlers = {"a": [H1, H2], "b": [H1]}

        dispatch_events_sync(["a", "b"], lambda event: handlers[event])

        # Every (event, handler) pair ran, event-major and in handler order.
        assert seen == [("h1", "a"), ("h2", "a"), ("h1", "b")]
        assert getattr(g, "_sync_dispatch_queue", None) is None
        assert getattr(g, "_sync_dispatch_draining", False) is False


def test_none_context_is_removed_not_stored_as_none(test_domain):
    """A captured context of ``None`` means 'no message in context': the drain
    removes the key for the handler's scope rather than setting it to ``None``,
    matching the command processor / engine save-restore convention. Storing
    ``None`` would leave a spurious key that a downstream ``x in g`` check treats
    as a real (empty) context."""
    with test_domain.domain_context():
        # No message_in_context is set: the key is absent on g.
        g.pop("message_in_context", None)
        sentinel = object()
        during = []

        class Handler:
            @classmethod
            def _handle(cls, event):
                during.append(g.get("message_in_context", sentinel))

        enqueue_sync_dispatch("e", Handler)  # captures a context of None
        drain_sync_dispatch()

        # The handler ran with the key genuinely absent, not present-as-None
        # (get() with a default distinguishes the two).
        assert during == [sentinel]
        # And it is still absent afterwards.
        assert "message_in_context" not in g


# --- Sibling handler-class failure isolation (ADR-0031) -------------------------
#
# Each (event, handler_cls) pair is an independent reaction. A failing class must
# not abort the drain and discard the classes queued behind it — the guarantee
# async already has, brought to sync.


def test_a_failing_class_no_longer_skips_the_classes_behind_it(test_domain):
    """The first class raising used to abort the drain and throw away the rest.
    Now every class runs and the failures surface together as a group."""
    with test_domain.domain_context():
        ran = []

        class A:
            @classmethod
            def _handle(cls, event):
                ran.append("A")
                raise RuntimeError("A boom")

        class B:
            @classmethod
            def _handle(cls, event):
                ran.append("B")

        class C:
            @classmethod
            def _handle(cls, event):
                ran.append("C")
                raise ValueError("C boom")

        enqueue_sync_dispatch("e", A)
        enqueue_sync_dispatch("e", B)
        enqueue_sync_dispatch("e", C)
        with pytest.raises(ExceptionGroup) as exc_info:
            drain_sync_dispatch()

        # Every class ran, in order — none skipped by the earlier failure.
        assert ran == ["A", "B", "C"]
        # Both failures are carried, the successful class contributes none.
        members = [type(e).__name__ for e in exc_info.value.exceptions]
        assert members == ["RuntimeError", "ValueError"]
        # The operator-facing group message names how many classes failed.
        assert (
            exc_info.value.message == "Synchronous dispatch: 2 handler classes failed"
        )
        # A clean drain even after a group is raised.
        assert getattr(g, "_sync_dispatch_queue", None) is None
        assert getattr(g, "_sync_dispatch_draining", False) is False


def test_a_single_class_failure_keeps_its_own_type(test_domain):
    """A lone failure propagates as itself rather than wrapped in a one-member
    group — and the class queued behind the failing one still runs."""
    with test_domain.domain_context():
        ran = []

        class Solo:
            @classmethod
            def _handle(cls, event):
                ran.append("solo")
                raise KeyError("solo")

        class Fine:
            @classmethod
            def _handle(cls, event):
                ran.append("fine")

        enqueue_sync_dispatch("e", Solo)
        enqueue_sync_dispatch("e", Fine)
        with pytest.raises(KeyError, match="solo"):
            drain_sync_dispatch()

        # The sibling behind the failing class still ran, and the failure kept
        # its own type rather than becoming a one-member group.
        assert ran == ["solo", "fine"]


def test_expected_version_error_is_collected_like_any_failure(test_domain, caplog):
    """An ExpectedVersionError does not end the drain. The drain runs after the
    enclosing commit has saved its writes, so the conflict is collected with the
    other failures and every class behind it still runs."""
    with test_domain.domain_context():
        ran = []

        class A:
            @classmethod
            def _handle(cls, event):
                ran.append("A")
                raise RuntimeError("A boom")

        class Conflict:
            @classmethod
            def _handle(cls, event):
                ran.append("Conflict")
                raise ExpectedVersionError("stale")

        class After:
            @classmethod
            def _handle(cls, event):
                ran.append("After")

        enqueue_sync_dispatch("e", A)
        enqueue_sync_dispatch("e", Conflict)
        enqueue_sync_dispatch("e", After)
        with caplog.at_level(logging.ERROR):
            with pytest.raises(ExceptionGroup) as exc_info:
                drain_sync_dispatch()

        assert ran == ["A", "Conflict", "After"]
        members = exc_info.value.exceptions
        assert [type(e) for e in members] == [RuntimeError, ExpectedVersionError]
        assert str(members[1]) == "stale"
        # Nothing was discarded, so there is no note and no discarded-failures log.
        assert getattr(members[1], "__notes__", []) == []
        assert "sync_dispatch.sibling_failures_discarded" not in caplog.text
        assert getattr(g, "_sync_dispatch_queue", None) is None
        assert getattr(g, "_sync_dispatch_draining", False) is False


def test_a_lone_expected_version_error_keeps_its_own_type(test_domain):
    """A conflict that is the only failure propagates as itself, like any other
    lone failure, and the class behind it still runs."""
    with test_domain.domain_context():
        ran = []

        class Conflict:
            @classmethod
            def _handle(cls, event):
                ran.append("Conflict")
                raise ExpectedVersionError("stale")

        class After:
            @classmethod
            def _handle(cls, event):
                ran.append("After")

        enqueue_sync_dispatch("e", Conflict)
        enqueue_sync_dispatch("e", After)
        with pytest.raises(ExpectedVersionError, match="stale") as exc_info:
            drain_sync_dispatch()

        assert ran == ["Conflict", "After"]
        assert getattr(exc_info.value, "__notes__", []) == []


def test_base_exception_ends_the_drain_at_once(test_domain, caplog):
    """A BaseException that is not an Exception — an interrupt — is never
    collected: it stops the drain immediately and carries the discarded
    failures, so nothing swallows the interrupt."""
    with test_domain.domain_context():
        ran = []

        class A:
            @classmethod
            def _handle(cls, event):
                ran.append("A")
                raise RuntimeError("A boom")

        class Interrupt:
            @classmethod
            def _handle(cls, event):
                ran.append("Interrupt")
                raise KeyboardInterrupt

        class Never:
            @classmethod
            def _handle(cls, event):
                ran.append("Never")

        enqueue_sync_dispatch("e", A)
        enqueue_sync_dispatch("e", Interrupt)
        enqueue_sync_dispatch("e", Never)
        with (
            caplog.at_level(logging.ERROR, logger="protean.utils.sync_dispatch"),
            pytest.raises(KeyboardInterrupt) as exc_info,
        ):
            drain_sync_dispatch()

        assert ran == ["A", "Interrupt"]
        discarded = [
            r
            for r in caplog.records
            if r.getMessage().startswith("sync_dispatch.sibling_failures_discarded")
        ]
        assert len(discarded) == 1
        assert discarded[0].levelno == logging.ERROR
        notes = getattr(exc_info.value, "__notes__", [])
        assert any("RuntimeError" in note for note in notes)
        assert getattr(g, "_sync_dispatch_queue", None) is None
        assert getattr(g, "_sync_dispatch_draining", False) is False


class _Interrupt(KeyboardInterrupt):
    pass


def test_a_discarded_failure_with_a_broken_str_does_not_break_the_drain(test_domain):
    """End-to-end robustness: a collected failure whose ``__str__`` raises does not
    stop an interrupt from propagating as itself. (``describe_exception`` renders
    the broken member as ``<unprintable>``, so this exercises the note path without
    tripping the guard around ``add_note``, which is covered separately below.)"""
    with test_domain.domain_context():

        class Nasty(Exception):
            def __str__(self):
                raise RuntimeError("cannot render me")

        class A:
            @classmethod
            def _handle(cls, event):
                raise Nasty()

        class Stop:
            @classmethod
            def _handle(cls, event):
                raise _Interrupt("stop")

        enqueue_sync_dispatch("e", A)
        enqueue_sync_dispatch("e", Stop)
        # The interrupt still propagates as itself, unharmed by the broken
        # __str__ on the discarded failure.
        with pytest.raises(_Interrupt, match="stop") as exc_info:
            drain_sync_dispatch()

        notes = getattr(exc_info.value, "__notes__", [])
        assert any("<unprintable>" in note for note in notes)


def test_a_failing_add_note_does_not_replace_the_propagating_exception(test_domain):
    """The note-attach is best-effort: if ``add_note`` on the propagating exception
    raises (here because its ``__notes__`` is not a list) the guard logs that at
    debug level, and the original interrupt still leaves the drain. Without the
    guard, ``add_note``'s ``TypeError`` would replace it and swallow the
    interrupt."""
    with test_domain.domain_context():

        class A:
            @classmethod
            def _handle(cls, event):
                raise RuntimeError("A boom")

        class Stop:
            @classmethod
            def _handle(cls, event):
                exc = _Interrupt("stop")
                # A non-list __notes__ makes exc.add_note(...) raise TypeError.
                exc.__notes__ = "not a list"
                raise exc

        enqueue_sync_dispatch("e", A)
        enqueue_sync_dispatch("e", Stop)
        with pytest.raises(_Interrupt, match="stop"):
            drain_sync_dispatch()


def test_reactions_enqueued_by_a_committed_class_still_drain_after_a_sibling_fails(
    test_domain,
):
    """A class that succeeds and enqueues its own reaction, next to a sibling that
    fails: the reaction must still run. Independence means the failure isolates,
    not that the queue is abandoned."""
    with test_domain.domain_context():
        ran = []

        class Downstream:
            @classmethod
            def _handle(cls, event):
                ran.append(("downstream", event))

        class Succeeds:
            @classmethod
            def _handle(cls, event):
                ran.append(("succeeds", event))
                enqueue_sync_dispatch("nested", Downstream)
                drain_sync_dispatch()  # nested — a no-op, outer drain runs it

        class Fails:
            @classmethod
            def _handle(cls, event):
                ran.append(("fails", event))
                raise RuntimeError("boom")

        enqueue_sync_dispatch("first", Succeeds)
        enqueue_sync_dispatch("first", Fails)
        with pytest.raises(RuntimeError, match="boom"):
            drain_sync_dispatch()

        assert ran == [
            ("succeeds", "first"),
            ("fails", "first"),
            ("downstream", "nested"),
        ]


def test_a_failing_class_that_enqueued_a_reaction_still_lets_it_drain(test_domain):
    """The reverse of the previous test: a class enqueues a reaction and *then*
    raises. Under the old abort-on-first-failure drain that reaction never ran;
    now it does, which is the "side effect a failure used to suppress" case the
    changelog warns about."""
    with test_domain.domain_context():
        ran = []

        class Downstream:
            @classmethod
            def _handle(cls, event):
                ran.append(("downstream", event))

        class FailsAfterEnqueue:
            @classmethod
            def _handle(cls, event):
                ran.append(("fails", event))
                enqueue_sync_dispatch("nested", Downstream)
                drain_sync_dispatch()  # nested — a no-op, outer drain runs it
                raise RuntimeError("boom")

        enqueue_sync_dispatch("first", FailsAfterEnqueue)
        with pytest.raises(RuntimeError, match="boom"):
            drain_sync_dispatch()

        # The reaction it enqueued before failing still ran.
        assert ran == [("fails", "first"), ("downstream", "nested")]


def test_a_multi_method_class_contributes_a_nested_sub_group(test_domain):
    """A handler class whose own dispatch raises an ``ExceptionGroup`` (several of
    its ``@handle`` methods failed) is collected as one member, so a second
    failing class produces a group nested one level deep. ``except*`` recurses
    into it; a one-level walk of ``.exceptions`` would stop at the sub-group."""
    with test_domain.domain_context():

        class MultiMethod:
            @classmethod
            def _handle(cls, event):
                raise ExceptionGroup(
                    "two methods failed", [KeyError("m1"), IndexError("m2")]
                )

        class Other:
            @classmethod
            def _handle(cls, event):
                raise ValueError("other")

        enqueue_sync_dispatch("e", MultiMethod)
        enqueue_sync_dispatch("e", Other)
        with pytest.raises(ExceptionGroup) as exc_info:
            drain_sync_dispatch()

        outer = exc_info.value
        assert [type(m).__name__ for m in outer.exceptions] == [
            "ExceptionGroup",
            "ValueError",
        ]
        # The first member is the class's own group, kept intact (nested).
        assert isinstance(outer.exceptions[0], ExceptionGroup)
        assert [type(m).__name__ for m in outer.exceptions[0].exceptions] == [
            "KeyError",
            "IndexError",
        ]


def test_failures_across_different_events_collect_into_one_group(test_domain):
    """The ``failures`` list is scoped to the whole drain, not reset per event, so
    a class failing on one event and another failing on a different event land in
    a single group."""
    with test_domain.domain_context():

        class AFails:
            @classmethod
            def _handle(cls, event):
                raise RuntimeError(f"A:{event}")

        class BFails:
            @classmethod
            def _handle(cls, event):
                raise ValueError(f"B:{event}")

        enqueue_sync_dispatch("e1", AFails)
        enqueue_sync_dispatch("e2", BFails)
        with pytest.raises(ExceptionGroup) as exc_info:
            drain_sync_dispatch()

        assert [type(m).__name__ for m in exc_info.value.exceptions] == [
            "RuntimeError",
            "ValueError",
        ]


def test_no_discarded_log_on_the_normal_group_path(test_domain, caplog):
    """The discarded-failures ERROR log fires only when a carve-out ends the
    drain early. On the ordinary path, where the collected failures ARE raised in
    the group, nothing was discarded, so it must not fire."""
    with test_domain.domain_context():

        class A:
            @classmethod
            def _handle(cls, event):
                raise RuntimeError("A boom")

        class B:
            @classmethod
            def _handle(cls, event):
                raise ValueError("B boom")

        enqueue_sync_dispatch("e", A)
        enqueue_sync_dispatch("e", B)
        # Capture from DEBUG up, so the negative assertion holds even if a
        # regression emitted the discard record at a lower level than ERROR.
        with caplog.at_level(logging.DEBUG):
            with pytest.raises(ExceptionGroup):
                drain_sync_dispatch()

        assert "sync_dispatch.sibling_failures_discarded" not in caplog.text


class _RaisingFilter(logging.Filter):
    def filter(self, record):
        raise RuntimeError("filter broke")


def test_a_note_that_cannot_be_added_is_logged(caplog):
    interrupt = KeyboardInterrupt("stop")
    interrupt.__notes__ = "not a list"

    with caplog.at_level(logging.DEBUG, logger="protean.utils.sync_dispatch"):
        _carry_discarded_failures([ValueError("x")], interrupt)

    assert interrupt.__notes__ == "not a list"
    assert any(
        record.getMessage().startswith("Could not note the discarded failures")
        for record in caplog.records
    )


def test_a_log_call_that_fails_is_reported_on_stderr(capsys):
    dispatch_logger = logging.getLogger("protean.utils.sync_dispatch")
    broken = _RaisingFilter()
    dispatch_logger.addFilter(broken)
    try:
        _carry_discarded_failures([ValueError("x")], KeyboardInterrupt("stop"))
    finally:
        dispatch_logger.removeFilter(broken)

    assert capsys.readouterr().err == (
        "Warning: could not log 1 discarded handler failures: "
        "RuntimeError: filter broke\n"
    )
