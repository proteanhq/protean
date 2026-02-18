"""Tests for the multi-worker Supervisor.

The Supervisor spawns child processes, so these tests exercise initialization,
validation, signal handling, and shutdown logic without spawning real workers.
"""

import signal
from unittest.mock import MagicMock, patch

import pytest

from protean.server.supervisor import Supervisor


class TestSupervisorInit:
    def test_initialization_with_valid_args(self):
        supervisor = Supervisor(
            domain_path="my.domain", num_workers=4, test_mode=True, debug=True
        )
        assert supervisor.domain_path == "my.domain"
        assert supervisor.num_workers == 4
        assert supervisor.test_mode is True
        assert supervisor.debug is True
        assert supervisor.workers == []
        assert supervisor.exit_code == 0
        assert supervisor._shutting_down is False

    def test_raises_on_zero_workers(self):
        with pytest.raises(ValueError, match="num_workers must be >= 1"):
            Supervisor(domain_path="d", num_workers=0)

    def test_raises_on_negative_workers(self):
        with pytest.raises(ValueError, match="num_workers must be >= 1"):
            Supervisor(domain_path="d", num_workers=-1)

    def test_defaults(self):
        supervisor = Supervisor(domain_path="d", num_workers=1)
        assert supervisor.test_mode is False
        assert supervisor.debug is False


class TestSupervisorSignalHandling:
    def test_install_signal_handlers(self):
        supervisor = Supervisor(domain_path="d", num_workers=1)
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        try:
            supervisor._install_signal_handlers()
            # After installing, signal handlers should be the supervisor's method
            assert signal.getsignal(signal.SIGINT) == supervisor._handle_signal
            assert signal.getsignal(signal.SIGTERM) == supervisor._handle_signal
        finally:
            # Restore original handlers
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

    def test_handle_signal_sets_shutting_down(self):
        supervisor = Supervisor(domain_path="d", num_workers=1)
        supervisor._shutdown_workers = MagicMock()

        supervisor._handle_signal(signal.SIGTERM, None)

        assert supervisor._shutting_down is True
        supervisor._shutdown_workers.assert_called_once()

    def test_handle_signal_idempotent(self):
        """Second signal is ignored when already shutting down."""
        supervisor = Supervisor(domain_path="d", num_workers=1)
        supervisor._shutdown_workers = MagicMock()

        supervisor._handle_signal(signal.SIGTERM, None)
        supervisor._handle_signal(signal.SIGTERM, None)

        # Only called once despite two signals
        supervisor._shutdown_workers.assert_called_once()


class TestSupervisorShutdownWorkers:
    def test_sends_sigterm_to_living_workers(self):
        supervisor = Supervisor(domain_path="d", num_workers=2)

        mock_worker1 = MagicMock()
        mock_worker1.is_alive.return_value = True
        mock_worker1.pid = 12345
        mock_worker1.name = "worker-0"

        mock_worker2 = MagicMock()
        mock_worker2.is_alive.return_value = True
        mock_worker2.pid = 12346
        mock_worker2.name = "worker-1"

        supervisor.workers = [mock_worker1, mock_worker2]

        with patch("os.kill") as mock_kill:
            supervisor._shutdown_workers()

            assert mock_kill.call_count == 2
            mock_kill.assert_any_call(12345, signal.SIGTERM)
            mock_kill.assert_any_call(12346, signal.SIGTERM)

    def test_handles_process_lookup_error(self):
        """Shutdown tolerates workers that already exited."""
        supervisor = Supervisor(domain_path="d", num_workers=1)

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = True
        mock_worker.pid = 99999
        mock_worker.name = "worker-0"
        supervisor.workers = [mock_worker]

        with patch("os.kill", side_effect=ProcessLookupError):
            # Should not raise
            supervisor._shutdown_workers()

        assert len(supervisor.workers) == 0

    def test_kills_workers_that_exceed_timeout(self):
        """Workers that don't stop in time get SIGKILL."""
        supervisor = Supervisor(domain_path="d", num_workers=1)

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = True
        mock_worker.pid = 12345
        mock_worker.name = "worker-0"
        # join returns without stopping the worker, is_alive still True
        mock_worker.join.return_value = None

        supervisor.workers = [mock_worker]

        with patch("os.kill"):
            supervisor._shutdown_workers()

            mock_worker.kill.assert_called_once()

    def test_skips_dead_workers(self):
        """Workers that are already dead are not sent signals."""
        supervisor = Supervisor(domain_path="d", num_workers=1)

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False
        mock_worker.pid = 12345
        mock_worker.name = "worker-0"
        supervisor.workers = [mock_worker]

        with patch("os.kill") as mock_kill:
            supervisor._shutdown_workers()
            mock_kill.assert_not_called()


class TestSupervisorMonitor:
    def test_monitor_detects_clean_exit(self):
        """Monitor detects worker clean exit and removes it."""
        supervisor = Supervisor(domain_path="d", num_workers=1)

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False
        mock_worker.exitcode = 0
        mock_worker.name = "worker-0"
        mock_worker.pid = 12345
        supervisor.workers = [mock_worker]

        supervisor._monitor()

        assert len(supervisor.workers) == 0
        assert supervisor.exit_code == 0

    def test_monitor_detects_crash(self):
        """Monitor sets exit_code=1 when a worker crashes."""
        supervisor = Supervisor(domain_path="d", num_workers=1)

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = False
        mock_worker.exitcode = 1
        mock_worker.name = "worker-0"
        mock_worker.pid = 12345
        supervisor.workers = [mock_worker]

        supervisor._monitor()

        assert supervisor.exit_code == 1

    def test_monitor_handles_keyboard_interrupt(self):
        """Monitor catches KeyboardInterrupt and shuts down."""
        supervisor = Supervisor(domain_path="d", num_workers=1)
        supervisor._shutdown_workers = MagicMock()

        mock_worker = MagicMock()
        mock_worker.is_alive.side_effect = KeyboardInterrupt
        mock_worker.name = "worker-0"
        mock_worker.pid = 12345
        supervisor.workers = [mock_worker]

        supervisor._monitor()

        assert supervisor._shutting_down is True
        supervisor._shutdown_workers.assert_called_once()


class TestSupervisorRun:
    def test_run_spawns_workers_and_monitors(self):
        """run() spawns workers and enters the monitor loop."""
        supervisor = Supervisor(domain_path="d", num_workers=2)

        mock_process = MagicMock()
        mock_process.pid = 12345

        mock_ctx = MagicMock()
        mock_ctx.Process.return_value = mock_process

        with patch("multiprocessing.get_context", return_value=mock_ctx):
            supervisor._monitor = MagicMock()
            supervisor.run()

            assert mock_ctx.Process.call_count == 2
            assert mock_process.start.call_count == 2
            assert len(supervisor.workers) == 2
            supervisor._monitor.assert_called_once()
