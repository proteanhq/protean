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

import contextlib
import logging
import multiprocessing
import os
import signal
import threading
from collections.abc import Sequence
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any

from watchfiles import PythonFilter, watch

from protean._deprecation import warn_from_registry
from protean.server.supervisor import (
    _check_log_arguments,
    _config_search_root,
    _join_within,
    _termination_budget,
    _worker_entry,
)

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
        log_level: str | None = None,
        log_format: str | None = None,
        log_config: dict[str, Any] | None = None,
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
            debug: Deprecated, removed in v0.20.0. ``True`` is the same as
                ``log_level="DEBUG"``; an explicit ``log_level`` wins.
            log_level: Log level the inner worker passes to
                ``Domain.configure_logging()`` in place of ``[logging].level``.
            log_format: Log format the inner worker passes to
                ``Domain.configure_logging()`` in place of ``[logging].format``.
            log_config: A ``logging.config.dictConfig`` dict. The inner worker
                applies it and skips ``Domain.configure_logging()``.
        """
        log_level, log_format = _check_log_arguments(log_level, log_format)
        if debug:
            warn_from_registry("reloader_debug", "Reloader(debug=...)")
            if log_level is None:
                log_level = "DEBUG"
        self.domain_path = domain_path
        self.test_mode = test_mode
        self.log_level = log_level
        self.log_format = log_format
        self.log_config = log_config

        resolved = list(reload_dirs) if reload_dirs else [Path.cwd()]
        self.reload_dirs: list[Path] = [Path(d).resolve() for d in resolved]

        self.exit_code: int = 0
        self.should_exit: threading.Event = threading.Event()
        self.process: BaseProcess | None = None
        self._ctx = multiprocessing.get_context("spawn")
        self._shutting_down: bool = False
        self._stop_timeout: float | None = None

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
        # Bind the join budget to this worker from the config as it stands now,
        # so a later domain.toml edit does not leave _stop_process joining it
        # with a stale window. The worker reads the same config at its own
        # startup, so the two match. Reading the file has no domain side effect.
        self._stop_timeout = self._termination_timeout()

        process = self._ctx.Process(
            target=_worker_entry,
            args=(self.domain_path, self.test_mode, 0, None),
            kwargs={
                "log_level": self.log_level,
                "log_format": self.log_format,
                "log_config": self.log_config,
            },
            name="protean-reload-worker",
        )
        process.start()
        self.process = process
        logger.info("Started Engine worker (PID %s)", process.pid)

    def _config_search_root(self) -> str:
        """Where to search for the project config the worker will read.

        See :func:`protean.server.supervisor._config_search_root`.
        """
        return _config_search_root(self.domain_path)

    def _termination_timeout(self) -> float:
        """How long to wait for a worker to exit before killing it.

        The configured drain window plus a margin, never less than the
        10-second default.

        Read fresh each time so a ``domain.toml`` edit that lands mid-run is
        picked up: ``_start_process`` calls this to bind the budget to the
        worker it is about to spawn, matching the window that worker will read
        at its own startup. A cached budget would join the next worker with a
        stale window and could kill it before its drain elapses.
        """
        return _termination_budget(self.domain_path, _SHUTDOWN_TIMEOUT_SECONDS)

    def _stop_process(self) -> None:
        """Terminate and join the current inner Engine process, if any."""
        process = self.process
        if process is None:
            return

        if process.is_alive() and process.pid:
            with contextlib.suppress(ProcessLookupError, OSError):
                os.kill(process.pid, signal.SIGTERM)

        # Use the budget bound to this worker when it started, so a config edit
        # since then does not shorten the join for a worker still draining on
        # its old window. Fall back to a fresh read if we stop before starting.
        timeout = self._stop_timeout
        if timeout is None:
            timeout = self._termination_timeout()
        _join_within(process, timeout)
        if process.is_alive():
            logger.warning(
                "Engine worker did not stop within %gs timeout, killing",
                timeout,
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
        # SIGHUP is unavailable on non-POSIX platforms.
        with contextlib.suppress(OSError, AttributeError):  # pragma: no cover
            signal.signal(signal.SIGHUP, self._handle_signal)

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
