"""Unit tests for the breadth-first synchronous dispatch helper (ADR-0016)."""

import pytest

from protean.utils.globals import g
from protean.utils.sync_dispatch import (
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
