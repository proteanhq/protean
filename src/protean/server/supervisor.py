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
import multiprocessing
import os
import signal
import sys
import time

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

        # Spawn all workers
        for worker_id in range(self.num_workers):
            process = ctx.Process(
                target=_worker_entry,
                args=(self.domain_path, self.test_mode, self.debug, worker_id),
                name=f"protean-worker-{worker_id}",
            )
            process.start()
            self.workers.append(process)
            logger.info(f"Started worker {worker_id} (PID {process.pid})")

        # Block in the monitor loop until all workers exit
        self._monitor()

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


def _worker_entry(
    domain_path: str,
    test_mode: bool,
    debug: bool,
    worker_id: int,
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
    """
    from protean.server.engine import Engine
    from protean.utils.domain_discovery import derive_domain
    from protean.utils.logging import configure_logging

    configure_logging(level="DEBUG" if debug else "INFO")

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

        engine = Engine(domain, test_mode=test_mode, debug=debug)
        engine.run()

        sys.exit(engine.exit_code)
    except Exception as exc:
        worker_logger.exception(f"Worker {worker_id} failed: {exc}")
        sys.exit(1)
