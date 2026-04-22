"""Multi-worker supervisor for the Protean Engine.

Follows the prefork model: spawns N worker processes, each running an
independent Engine instance with its own event loop and domain initialization.

Workers coordinate implicitly through:
- Redis consumer groups (StreamSubscription) — messages are distributed
- Database-level locking (OutboxProcessor) — prevents duplicate processing

No IPC or shared memory is needed between workers.

Usage:
    # From Protean CLI
    protean server --domain my.domain --workers 4

    # Programmatic
    supervisor = Supervisor("my.domain", num_workers=4)
    supervisor.run()
"""

import logging
import logging.handlers
import multiprocessing
import os
import signal
import sys
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SHUTDOWN_TIMEOUT_SECONDS = 30


class Supervisor:
    """Spawns and monitors N Engine worker processes.

    Each worker independently derives, initializes, and runs an Engine for the
    given domain. The Supervisor handles:

    - Spawning workers using the ``spawn`` multiprocessing start method
    - Propagating shutdown signals (SIGINT, SIGTERM) to all workers
    - Monitoring workers and detecting crashes
    - Enforcing a shutdown timeout with SIGKILL as a last resort
    - In multi-worker mode, running a ``QueueListener`` on the supervisor so
      worker log lines never interleave at byte boundaries (long JSON records
      from separate processes can otherwise corrupt each other since stdout
      writes above ``PIPE_BUF`` are not atomic)
    """

    def __init__(
        self,
        domain_path: str,
        num_workers: int,
        test_mode: bool = False,
        debug: bool = False,
    ) -> None:
        """Initialize the Supervisor.

        Args:
            domain_path: A ``derive_domain``-compatible string that resolves to
                a Protean Domain (e.g. ``"identity.domain"``).
            num_workers: Number of worker processes to spawn.
            test_mode: If True, each worker Engine runs in test mode
                (limited cycles, then exit).
            debug: If True, workers run with DEBUG-level logging.
        """
        if num_workers < 1:
            raise ValueError("num_workers must be >= 1")

        self.domain_path = domain_path
        self.num_workers = num_workers
        self.test_mode = test_mode
        self.debug = debug

        self.workers: list[multiprocessing.Process] = []
        self.exit_code: int = 0
        self._shutting_down: bool = False

        # Log queue plumbing — only populated in multi-worker mode. The queue
        # is created from the spawn context so it is safe to share with child
        # processes; the listener runs on the supervisor and owns the real
        # stream/file handlers.
        self._log_queue: Optional[Any] = None  # type: ignore[assignment]
        self._queue_listener: Optional[logging.handlers.QueueListener] = None

    def run(self) -> None:
        """Spawn workers and block until all have exited."""
        # Use 'spawn' start method for safety on all platforms.
        # Avoids fork-related issues with asyncio event loops, database
        # connections, and other non-fork-safe resources.
        ctx = multiprocessing.get_context("spawn")

        self._install_signal_handlers()

        logger.info(
            f"Starting Supervisor with {self.num_workers} worker(s) "
            f"for domain '{self.domain_path}'"
        )

        # In multi-worker mode, set up a QueueListener on the supervisor so
        # that all worker log records are serialized through a single sink.
        if self.num_workers > 1:
            self._log_queue = ctx.Queue(-1)
            self._queue_listener = _build_queue_listener(self._log_queue)
            self._queue_listener.start()

        # Spawn all workers
        for worker_id in range(self.num_workers):
            process = ctx.Process(
                target=_worker_entry,
                args=(
                    self.domain_path,
                    self.test_mode,
                    self.debug,
                    worker_id,
                    self._log_queue,
                ),
                name=f"protean-worker-{worker_id}",
            )
            process.start()
            self.workers.append(process)
            logger.info(f"Started worker {worker_id} (PID {process.pid})")

        # Block in the monitor loop until all workers exit
        try:
            self._monitor()
        finally:
            # Drain and stop the listener so any buffered records are flushed
            # before the supervisor exits.
            if self._queue_listener is not None:
                try:
                    self._queue_listener.stop()
                except Exception:
                    logger.exception("supervisor.queue_listener_stop_failed")
                self._queue_listener = None

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install signal handlers in the supervisor process."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        try:
            signal.signal(signal.SIGHUP, self._handle_signal)
        except (OSError, AttributeError):
            pass  # SIGHUP not available on Windows

    def _handle_signal(self, signum, frame) -> None:
        """Propagate shutdown to all workers on receiving a signal."""
        if self._shutting_down:
            return
        self._shutting_down = True

        sig_name = signal.Signals(signum).name
        logger.info(f"Supervisor received {sig_name}, shutting down workers...")
        self._shutdown_workers()

    # ------------------------------------------------------------------
    # Worker monitoring
    # ------------------------------------------------------------------

    def _monitor(self) -> None:
        """Monitor workers and wait for them to exit.

        Detects worker crashes, logs them, and continues monitoring the
        remaining workers. Exits when all workers have stopped.
        """
        try:
            while self.workers and not self._shutting_down:
                for worker in list(self.workers):
                    if not worker.is_alive():
                        worker.join(timeout=1)
                        self.workers.remove(worker)
                        if worker.exitcode != 0 and not self._shutting_down:
                            logger.error(
                                f"Worker {worker.name} (PID {worker.pid}) "
                                f"exited with code {worker.exitcode}"
                            )
                            self.exit_code = 1
                        else:
                            logger.info(f"Worker {worker.name} exited cleanly")
                time.sleep(0.5)
        except KeyboardInterrupt:
            if not self._shutting_down:
                self._shutting_down = True
                self._shutdown_workers()

        # Final cleanup: wait for any remaining workers after shutdown
        for worker in list(self.workers):
            worker.join(timeout=5)
            self.workers.remove(worker)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _shutdown_workers(self) -> None:
        """Send SIGTERM to all workers, wait with timeout, then SIGKILL."""
        # Send SIGTERM to each living worker
        for worker in self.workers:
            if worker.is_alive() and worker.pid:
                try:
                    os.kill(worker.pid, signal.SIGTERM)
                except (ProcessLookupError, OSError):
                    pass

        # Wait for workers to exit gracefully
        deadline = time.monotonic() + _SHUTDOWN_TIMEOUT_SECONDS
        for worker in list(self.workers):
            remaining = max(0, deadline - time.monotonic())
            worker.join(timeout=remaining)
            if worker.is_alive():
                logger.warning(
                    f"Worker {worker.name} did not stop within "
                    f"{_SHUTDOWN_TIMEOUT_SECONDS}s timeout, killing"
                )
                worker.kill()
                worker.join(timeout=5)
            self.workers.remove(worker)

        logger.info("All workers have been shut down")


def _build_queue_listener(queue: Any) -> logging.handlers.QueueListener:
    """Construct a ``QueueListener`` bound to the supervisor's real handlers.

    Copies the current root logger handlers (populated by
    :func:`protean.utils.logging.configure_logging`) so that worker log
    records flow through the same formatters the supervisor uses.  A stdout
    ``StreamHandler`` is installed as a fallback when the supervisor has no
    handlers configured, so worker logs still reach somewhere visible.
    """
    root = logging.getLogger()
    handlers = list(root.handlers)
    if not handlers:
        fallback = logging.StreamHandler(sys.stdout)
        fallback.setLevel(logging.INFO)
        handlers = [fallback]
    return logging.handlers.QueueListener(queue, *handlers, respect_handler_level=True)


def _install_worker_log_queue(queue: Any) -> None:
    """Install a ``QueueHandler`` as the sole root handler for this worker.

    Called from :func:`_worker_entry` after ``configure_logging()`` so the
    worker's real handlers are replaced by a single ``QueueHandler`` that
    funnels every record to the supervisor's listener.  Preserves filters
    (correlation/redaction) attached to the root logger by
    ``Domain.configure_logging()``.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.addHandler(logging.handlers.QueueHandler(queue))


def _worker_entry(
    domain_path: str,
    test_mode: bool,
    debug: bool,
    worker_id: int,
    log_queue: Optional[Any] = None,
) -> None:
    """Entry point for each spawned worker process.

    Each worker independently:
    1. Derives and initializes the domain from the string path
    2. Creates its own Engine instance with a dedicated event loop
    3. Runs the engine (blocking until shutdown signal)

    This function must be defined at module level (not as a method or lambda)
    so that it is picklable by the ``spawn`` multiprocessing start method.

    Args:
        domain_path: A ``derive_domain``-compatible string.
        test_mode: Run Engine in test mode.
        debug: Run Engine with DEBUG-level logging.
        worker_id: Numeric identifier for this worker (for logging).
        log_queue: Optional ``multiprocessing.Queue`` for forwarding log
            records to the supervisor's ``QueueListener``.  When ``None``
            (single-worker mode) the worker uses direct handlers from
            ``configure_logging()``.
    """
    from protean.server.engine import Engine
    from protean.utils.domain_discovery import derive_domain
    from protean.utils.logging import configure_logging

    configure_logging(level="DEBUG" if debug else "INFO")

    # Multi-worker mode: replace direct handlers with a QueueHandler so
    # records are serialized through the supervisor's listener.
    if log_queue is not None:
        _install_worker_log_queue(log_queue)

    worker_logger = logging.getLogger(f"protean.server.worker-{worker_id}")
    worker_logger.info(f"Worker {worker_id} (PID {os.getpid()}) starting...")

    try:
        domain = derive_domain(domain_path)
        if domain is None:
            worker_logger.error(
                f"Worker {worker_id}: Failed to derive domain from '{domain_path}'"
            )
            sys.exit(1)

        domain.init()

        with domain.domain_context():
            engine = Engine(domain, test_mode=test_mode, debug=debug)
            engine.run()

        sys.exit(engine.exit_code)
    except Exception as exc:
        worker_logger.exception(f"Worker {worker_id} failed: {exc}")
        sys.exit(1)
