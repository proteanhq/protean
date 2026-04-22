"""Tests for multi-worker log queue plumbing.

Verifies that:
- When ``num_workers > 1``, the supervisor creates a multiprocessing queue
  and starts a ``QueueListener`` on it.
- Each worker's root logger is configured with exactly one ``QueueHandler``
  as its sole handler.
- The listener is stopped during supervisor shutdown.
- ``num_workers == 1`` stays on direct handlers — no queue overhead.
"""

import logging
import logging.handlers
import multiprocessing
from unittest.mock import MagicMock, patch

import pytest

from protean.server.supervisor import (
    Supervisor,
    _build_queue_listener,
    _install_worker_log_queue,
    _worker_entry,
)


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

    def test_installs_single_queue_handler_as_sole_root_handler(self):
        root = logging.getLogger()
        saved = list(root.handlers)
        try:
            # Simulate workers' state after configure_logging — stream handler
            # plus maybe a file handler installed on root.
            root.handlers = [logging.StreamHandler(), logging.StreamHandler()]

            q: multiprocessing.Queue = multiprocessing.Queue(-1)
            _install_worker_log_queue(q)

            assert len(root.handlers) == 1
            assert isinstance(root.handlers[0], logging.handlers.QueueHandler)
            assert root.handlers[0].queue is q
        finally:
            root.handlers = saved

    def test_closes_previous_handlers(self):
        root = logging.getLogger()
        saved = list(root.handlers)
        try:
            tracker = MagicMock(spec=logging.Handler)
            root.handlers = [tracker]

            q: multiprocessing.Queue = multiprocessing.Queue(-1)
            _install_worker_log_queue(q)

            tracker.close.assert_called_once()
        finally:
            root.handlers = saved


class TestSupervisorLogQueueLifecycle:
    """End-to-end: the Supervisor spins up and tears down the listener."""

    def test_single_worker_does_not_create_log_queue(self):
        supervisor = Supervisor(domain_path="d", num_workers=1, test_mode=True)

        mock_process = MagicMock()
        mock_process.pid = 1
        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            supervisor._monitor = MagicMock()
            supervisor.run()

        assert supervisor._log_queue is None
        assert supervisor._queue_listener is None
        # _worker_entry args must still include the log_queue slot (None)
        call_args = mock_ctx.Process.call_args
        assert call_args.kwargs["args"][-1] is None

    def test_multi_worker_creates_queue_and_listener(self):
        supervisor = Supervisor(domain_path="d", num_workers=2, test_mode=True)

        mock_queue = MagicMock()
        mock_process = MagicMock()
        mock_process.pid = 1
        mock_ctx = MagicMock()
        mock_ctx.Queue.return_value = mock_queue
        mock_ctx.Process.return_value = mock_process

        mock_listener = MagicMock()

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch(
                "protean.server.supervisor._build_queue_listener",
                return_value=mock_listener,
            ),
        ):
            supervisor._monitor = MagicMock()
            supervisor.run()

        mock_ctx.Queue.assert_called_once_with(-1)
        mock_listener.start.assert_called_once()
        mock_listener.stop.assert_called_once()  # stopped on shutdown

        # Every Process constructed receives the queue in its args.
        for call in mock_ctx.Process.call_args_list:
            assert call.kwargs["args"][-1] is mock_queue

    def test_listener_stop_failure_is_swallowed(self):
        """A broken listener must not mask supervisor exit."""
        supervisor = Supervisor(domain_path="d", num_workers=2, test_mode=True)

        mock_queue = MagicMock()
        mock_process = MagicMock()
        mock_process.pid = 1
        mock_ctx = MagicMock()
        mock_ctx.Queue.return_value = mock_queue
        mock_ctx.Process.return_value = mock_process

        mock_listener = MagicMock()
        mock_listener.stop.side_effect = RuntimeError("listener broken")

        with (
            patch("multiprocessing.get_context", return_value=mock_ctx),
            patch(
                "protean.server.supervisor._build_queue_listener",
                return_value=mock_listener,
            ),
        ):
            supervisor._monitor = MagicMock()
            supervisor.run()  # must not raise

        mock_listener.stop.assert_called_once()


class TestWorkerEntryWithLogQueue:
    """``_worker_entry`` installs the QueueHandler when a queue is supplied."""

    def test_worker_entry_installs_queue_handler(self):
        """Worker with `log_queue != None` routes through `_install_worker_log_queue`."""
        q: multiprocessing.Queue = multiprocessing.Queue(-1)

        mock_domain = MagicMock()
        mock_domain.domain_context.return_value.__enter__ = MagicMock()
        mock_domain.domain_context.return_value.__exit__ = MagicMock(return_value=False)
        mock_engine = MagicMock()
        mock_engine.exit_code = 0

        with (
            patch(
                "protean.utils.domain_discovery.derive_domain",
                return_value=mock_domain,
            ),
            patch("protean.server.engine.Engine", return_value=mock_engine),
            patch("protean.utils.logging.configure_logging"),
            patch(
                "protean.server.supervisor._install_worker_log_queue"
            ) as mock_install,
            pytest.raises(SystemExit),
        ):
            _worker_entry("my.domain", True, False, 0, q)

        mock_install.assert_called_once_with(q)


class TestQueueListenerDrainsRecords:
    """The listener drains queued records into the underlying handlers."""

    def test_records_on_queue_are_processed_by_handlers(self):
        captured: list[logging.LogRecord] = []

        class _CapturingHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record)

        handler = _CapturingHandler(level=logging.DEBUG)

        import queue

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
