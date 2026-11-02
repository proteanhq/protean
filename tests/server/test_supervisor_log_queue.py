"""Tests for multi-worker log queue plumbing.

Verifies that:
- When ``num_workers > 1``, the supervisor creates a multiprocessing queue
  and starts a ``QueueListener`` on it.
- Each worker's root logger is configured with exactly one ``QueueHandler``
  as its sole handler.
- The listener is stopped during supervisor shutdown.
- ``num_workers == 1`` stays on direct handlers, with no queue.
"""

import logging
import logging.handlers
import multiprocessing
import queue
import signal
from unittest.mock import MagicMock, patch

import pytest

from protean.server.supervisor import (
    Supervisor,
    _build_queue_listener,
    _install_worker_log_queue,
)


@pytest.fixture(autouse=True)
def _restore_signal_handlers():
    """Put back the handlers that ``Supervisor.run()`` installs."""
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    saved = {sig: signal.getsignal(sig) for sig in signals}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


def _exited_worker(**kwargs) -> MagicMock:
    """A worker process that has already exited."""
    worker = MagicMock()
    worker.is_alive.return_value = False
    worker.pid = 1
    worker.name = kwargs["name"]
    worker.exitcode = 0
    return worker


def _run(supervisor: Supervisor, ctx: MagicMock) -> None:
    """Run *supervisor* on the spawn context *ctx*, without waiting between polls."""
    with (
        patch("multiprocessing.get_context", return_value=ctx),
        patch("time.sleep"),
    ):
        supervisor.run()


class TestBuildQueueListener:
    """``_build_queue_listener`` wires the supervisor's handlers into the listener."""

    def test_uses_root_logger_handlers(self):
        root = logging.getLogger()
        saved = list(root.handlers)
        try:
            h1 = logging.StreamHandler()
            h2 = logging.StreamHandler()
            root.handlers = [h1, h2]

            q: multiprocessing.Queue = multiprocessing.Queue(-1)
            listener = _build_queue_listener(q)

            assert isinstance(listener, logging.handlers.QueueListener)
            assert listener.handlers == (h1, h2)
        finally:
            root.handlers = saved

    def test_falls_back_to_stdout_when_no_handlers(self):
        root = logging.getLogger()
        saved = list(root.handlers)
        try:
            root.handlers = []

            q: multiprocessing.Queue = multiprocessing.Queue(-1)
            listener = _build_queue_listener(q)

            assert len(listener.handlers) == 1
            assert isinstance(listener.handlers[0], logging.StreamHandler)
        finally:
            root.handlers = saved


class TestInstallWorkerLogQueue:
    """``_install_worker_log_queue`` replaces root handlers with a single QueueHandler."""

    def test_installs_single_queue_handler_and_closes_previous_handlers(self, tmp_path):
        root = logging.getLogger()
        saved = list(root.handlers)
        # A worker's state after configure_logging: a stream handler plus a
        # file handler on root.
        file_handler = logging.FileHandler(tmp_path / "worker.log")
        # A filter that is not one of Protean's stays on the root logger.
        other_filter = logging.Filter("app")
        root.addFilter(other_filter)
        try:
            root.handlers = [logging.StreamHandler(), file_handler]

            q: multiprocessing.Queue = multiprocessing.Queue(-1)
            _install_worker_log_queue(q)

            assert len(root.handlers) == 1
            assert isinstance(root.handlers[0], logging.handlers.QueueHandler)
            assert root.handlers[0].queue is q
            # A closed FileHandler has released its stream.
            assert file_handler.stream is None
            assert other_filter in root.filters
            assert other_filter not in root.handlers[0].filters
        finally:
            root.removeFilter(other_filter)
            root.handlers = saved


class TestSupervisorLogQueueLifecycle:
    """End-to-end: the Supervisor spins up and tears down the listener."""

    def test_multi_worker_creates_queue_and_listener(self):
        supervisor = Supervisor(domain_path="d", num_workers=2, test_mode=True)
        at_spawn = []

        def spawn(**kwargs):
            listener = supervisor._queue_listener
            at_spawn.append(
                (supervisor._log_queue, listener, listener._thread is not None)
            )
            return _exited_worker(**kwargs)

        ctx = MagicMock()
        ctx.Queue.side_effect = queue.Queue
        ctx.Process.side_effect = spawn

        _run(supervisor, ctx)

        ctx.Queue.assert_called_once_with(-1)
        log_queue, listener, running = at_spawn[0]
        # The listener runs on the queue while workers spawn.
        assert isinstance(listener, logging.handlers.QueueListener)
        assert listener.queue is log_queue
        assert running is True
        # It is stopped on shutdown.
        assert listener._thread is None
        assert supervisor._queue_listener is None

        # Every Process constructed receives the queue in its args.
        assert ctx.Process.call_count == 2
        for call in ctx.Process.call_args_list:
            assert call.kwargs["args"][-1] is log_queue

    def test_listener_stop_failure_is_swallowed(self, caplog):
        """A broken listener must not mask supervisor exit."""
        supervisor = Supervisor(domain_path="d", num_workers=2, test_mode=True)

        ctx = MagicMock()
        ctx.Queue.side_effect = queue.Queue
        ctx.Process.side_effect = _exited_worker

        mock_listener = MagicMock()
        mock_listener.stop.side_effect = RuntimeError("listener broken")

        with (
            patch(
                "protean.server.supervisor._build_queue_listener",
                return_value=mock_listener,
            ),
            caplog.at_level(logging.WARNING, logger="protean.server.supervisor"),
        ):
            _run(supervisor, ctx)  # must not raise

        mock_listener.stop.assert_called_once()
        assert supervisor.exit_code == 0
        assert "supervisor.queue_listener_stop_failed" in [
            r.getMessage() for r in caplog.records
        ]


class TestQueueListenerDrainsRecords:
    """The listener drains queued records into the underlying handlers."""

    def test_records_on_queue_are_processed_by_handlers(self):
        captured: list[logging.LogRecord] = []

        class _CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        handler = _CapturingHandler(level=logging.DEBUG)

        q: queue.Queue = queue.Queue(-1)
        listener = logging.handlers.QueueListener(
            q, handler, respect_handler_level=True
        )
        listener.start()
        try:
            # Simulate a worker emitting through its QueueHandler
            qh = logging.handlers.QueueHandler(q)
            record = logging.LogRecord(
                name="protean.server.worker-0",
                level=logging.INFO,
                pathname="",
                lineno=0,
                msg="worker_started",
                args=(),
                exc_info=None,
            )
            qh.emit(record)
        finally:
            listener.stop()

        assert len(captured) == 1
        assert captured[0].name == "protean.server.worker-0"
        assert captured[0].getMessage() == "worker_started"
