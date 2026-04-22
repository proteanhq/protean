"""Development reloader for the Protean Engine.

Implements a file-watching development server that restarts the Engine
process automatically when source files change. Built on top of
``watchfiles`` (the same library uvicorn uses).

The reloader runs as an outer process that:

1. Spawns a single inner process running the Engine.
2. Watches one or more directories for Python file changes.
3. On change, terminates the inner process and spawns a replacement.
4. On ``SIGINT``/``SIGTERM``, gracefully shuts down the inner process
   and exits.

Files and directories matching common non-source patterns are ignored via
``watchfiles.PythonFilter`` (``.pyc``, ``__pycache__``, ``.venv``, ``.git``,
``node_modules``, etc.). The ``.protean/`` IR cache directory is also
ignored so that regenerated schema snapshots do not trigger a reload.

Usage::

    # From Protean CLI
    protean server --domain my.domain --reload

    # Programmatic
    reloader = Reloader("my.domain", reload_dirs=["src"])
    reloader.run()
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import signal
import threading
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Sequence

from watchfiles import PythonFilter, watch

from protean.server.supervisor import _worker_entry

logger = logging.getLogger(__name__)

_SHUTDOWN_TIMEOUT_SECONDS = 10

# Directories ignored in addition to the ``watchfiles`` defaults.
# ``.protean/`` holds generated IR caches that should never trigger a reload.
_EXTRA_IGNORE_DIRS: tuple[str, ...] = (".protean",)


class Reloader:
    """Outer process that restarts the Engine on file changes.

    Spawns a single inner Engine worker process, then uses ``watchfiles``
    to watch the configured directories for Python source changes. When a
    change is detected, terminates the current inner process and spawns a
    replacement.

    The reloader exits when it receives ``SIGINT`` or ``SIGTERM``.
    """

    def __init__(
        self,
        domain_path: str,
        reload_dirs: Sequence[str | Path] | None = None,
        test_mode: bool = False,
        debug: bool = False,
    ) -> None:
        """Initialize the Reloader.

        Args:
            domain_path: A ``derive_domain``-compatible string that
                resolves to a Protean Domain (e.g. ``"identity.domain"``).
            reload_dirs: Directories to watch for changes. Defaults to the
                current working directory when not supplied.
            test_mode: If ``True``, the inner Engine runs in test mode
                (limited cycles, then exits). Used to keep reloader smoke
                tests deterministic.
            debug: If ``True``, the inner Engine runs with DEBUG-level
                logging.
        """
        self.domain_path = domain_path
        self.test_mode = test_mode
        self.debug = debug

        resolved = list(reload_dirs) if reload_dirs else [Path.cwd()]
        self.reload_dirs: list[Path] = [Path(d).resolve() for d in resolved]

        self.exit_code: int = 0
        self.should_exit: threading.Event = threading.Event()
        self.process: BaseProcess | None = None
        self._ctx = multiprocessing.get_context("spawn")
        self._shutting_down: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Start the inner Engine and block until exit is requested."""
        self._install_signal_handlers()

        dir_list = ", ".join(str(d) for d in self.reload_dirs)
        startup_msg = f"Started reloader process [{os.getpid()}] watching {dir_list}"
        logger.info(startup_msg)
        print(startup_msg)

        self._start_process()

        # ``PythonFilter`` already excludes ``.pyc``, ``__pycache__``,
        # ``.venv``, ``node_modules``, etc. Extend it with Protean's own
        # IR cache directory so regenerated snapshots are not noisy.
        watch_filter = PythonFilter()
        watch_filter.ignore_dirs = tuple(watch_filter.ignore_dirs) + _EXTRA_IGNORE_DIRS

        try:
            for changes in watch(
                *self.reload_dirs,
                watch_filter=watch_filter,
                stop_event=self.should_exit,
                yield_on_timeout=True,
                raise_interrupt=False,
                ignore_permission_denied=True,
            ):
                if self.should_exit.is_set():
                    break
                if not changes:
                    continue

                paths = sorted({path for _change, path in changes})
                pretty = ", ".join(_display_path(p) for p in paths)
                reload_msg = f"Detected change in {pretty}, restarting..."
                logger.info(reload_msg)
                print(reload_msg)

                self._restart_process()
        finally:
            self._shutdown()

    # ------------------------------------------------------------------
    # Process lifecycle
    # ------------------------------------------------------------------

    def _start_process(self) -> None:
        """Spawn a new inner Engine worker process."""
        process = self._ctx.Process(
            target=_worker_entry,
            args=(self.domain_path, self.test_mode, self.debug, 0, None),
            name="protean-reload-worker",
        )
        process.start()
        self.process = process
        logger.info("Started Engine worker (PID %s)", process.pid)

    def _stop_process(self) -> None:
        """Terminate and join the current inner Engine process, if any."""
        process = self.process
        if process is None:
            return

        if process.is_alive() and process.pid:
            try:
                os.kill(process.pid, signal.SIGTERM)
            except (ProcessLookupError, OSError):
                pass

        process.join(timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        if process.is_alive():
            logger.warning(
                "Engine worker did not stop within %ds timeout, killing",
                _SHUTDOWN_TIMEOUT_SECONDS,
            )
            process.kill()
            process.join(timeout=5)

        if process.exitcode is not None and process.exitcode != 0:
            # Don't mask a crashing worker — surface it via the exit code
            # so the CLI can propagate it.
            self.exit_code = process.exitcode

        self.process = None

    def _restart_process(self) -> None:
        """Stop the current inner process and spawn a replacement."""
        self._stop_process()
        if self.should_exit.is_set():
            return
        # Clear a non-zero exit code from the previous generation so a
        # successful restart returns cleanly. A crash during shutdown is
        # re-captured in ``_shutdown``.
        self.exit_code = 0
        self._start_process()

    # ------------------------------------------------------------------
    # Signal handling / shutdown
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install SIGINT/SIGTERM handlers on the reloader process."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        try:
            signal.signal(signal.SIGHUP, self._handle_signal)
        except (OSError, AttributeError):  # pragma: no cover - non-POSIX
            pass

    def _handle_signal(self, signum: int, frame: object) -> None:
        """Request shutdown when the reloader receives a terminating signal."""
        if self._shutting_down:
            return
        self._shutting_down = True
        sig_name = signal.Signals(signum).name
        logger.info("Reloader received %s, shutting down", sig_name)
        self.should_exit.set()

    def _shutdown(self) -> None:
        """Stop the inner process and finalize the reloader lifecycle."""
        logger.info("Stopping reloader process [%d]", os.getpid())
        self._stop_process()


def _display_path(path: str) -> str:
    """Render a path relative to the working directory when possible."""
    try:
        return f"'{Path(path).relative_to(Path.cwd())}'"
    except ValueError:
        return f"'{path}'"
