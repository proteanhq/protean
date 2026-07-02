"""Unit tests for the breadth-first synchronous dispatch helper (ADR-0016)."""

import pytest

from protean.utils.globals import g
from protean.utils.sync_dispatch import drain_sync_dispatch, enqueue_sync_dispatch


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
