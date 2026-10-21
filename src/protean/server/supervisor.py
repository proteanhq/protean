"""Multi-worker supervisor for the Protean Engine.

Follows the prefork model: spawns N worker processes, each running an
independent Engine instance with its own event loop and domain initialization.

Workers coordinate implicitly through:
- Redis consumer groups (StreamSubscription) — messages are distributed
- Database-level locking (OutboxProcessor) — prevents duplicate processing

Event-store subscriptions (EventStoreSubscription) have no such cluster-wide
ownership: every worker reading the same stream processes the same events. They
are therefore single-writer, and the Supervisor refuses to spawn more than one
worker for a domain that has any — unless ``acknowledge_event_store_risk=True``.

No IPC or shared memory is needed between workers.

Usage:
    # From Protean CLI
    protean server --domain my.domain --workers 4

    # Programmatic. Worker records are written by the supervisor's own root
    # handlers, so set those up first.
    configure_logging(level="DEBUG")
    supervisor = Supervisor("my.domain", num_workers=4, log_level="DEBUG")
    supervisor.run()
"""

import contextlib
import logging
import logging.handlers
import math
import multiprocessing
import os
import re
import signal
import sys
import time
import warnings
from multiprocessing.process import BaseProcess
from types import FrameType
from typing import Any, Optional

from protean._deprecation import warn_from_registry
from protean.integrations.logging import ProteanRedactionFilter, _keep_record_context
from protean.utils.logging import (
    _PROTEAN_ROOT_FILTERS,
    _add_redaction_filter_if_uncovered,
    _install_root_filter,
    _move_redaction_filter_last,
)

logger = logging.getLogger(__name__)

_SHUTDOWN_TIMEOUT_SECONDS = 30

# Slack added on top of the Engine's drain window when sizing a shutdown
# budget: the worker still has to cancel stragglers, close brokers and
# providers, and exit after the window elapses.
_DRAIN_MARGIN_SECONDS = 5

# The values the CLI's ``--log-level`` and ``--log-format`` flags accept.
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LOG_FORMATS = ("auto", "console", "json")


def _check_log_arguments(
    log_level: str | None, log_format: str | None
) -> tuple[str | None, str | None]:
    """Validate ``log_level`` and ``log_format`` the way the CLI flags are.

    An empty string counts as not given. The level is upper-cased.

    Raises:
        ValueError: If a value is not one the CLI flags accept.
    """
    level = log_level.upper() if log_level else None
    if level is not None and level not in _LOG_LEVELS:
        raise ValueError(
            f"Invalid log_level {log_level!r}. Choose from: {', '.join(_LOG_LEVELS)}"
        )
    fmt = log_format or None
    if fmt is not None and fmt not in _LOG_FORMATS:
        raise ValueError(
            f"Invalid log_format {log_format!r}. Choose from: {', '.join(_LOG_FORMATS)}"
        )
    return level, fmt


def _config_search_root(domain_path: str) -> str:
    """Where to search for the project config, matching the worker's
    ``Domain.root_path`` resolution as closely as possible without
    importing the domain.

    The worker's Domain honours ``DOMAIN_ROOT_PATH`` and otherwise uses the
    directory of the domain module file (``_guess_caller_path``). Mirror
    that so the parent reads the same ``domain.toml`` the worker will, even
    when the server is launched from a different working directory. A
    dotted module name cannot be resolved to a file without importing it, so
    fall back to the working directory, where ``domain.toml`` conventionally
    lives.
    """
    env_root = os.environ.get("DOMAIN_ROOT_PATH")
    if env_root:
        return env_root

    domain_path = os.environ.get("PROTEAN_DOMAIN") or domain_path
    # Drop a ":factory" suffix; the left side is the module or file path.
    # Do not split a Windows drive letter or a URL scheme.
    path_part = re.split(r":(?![\\/])", domain_path, maxsplit=1)[0]
    candidate = os.path.realpath(path_part)
    if not os.path.splitext(candidate)[1] and os.path.isfile(candidate + ".py"):
        candidate += ".py"
    if os.path.isfile(candidate):
        return os.path.dirname(candidate)
    if os.path.isdir(candidate):
        return candidate
    return os.getcwd()


def _configured_drain_window(domain_path: str) -> float:
    """The worker Engine's ``[server].drain_timeout``, or 0 if unreadable.

    Read from the project config file so a shutdown budget matches the
    window the worker will wait, without importing or instantiating the
    domain here in the parent. Deriving the domain would re-run a
    factory-style ``domain_path`` (the worker already invokes it in the
    child), doubling resource initialisation in a process that only manages
    workers; reading the config file has no such side effect. The search
    starts from the same place the worker resolves its config (see
    ``_config_search_root``), not blindly from the working directory.

    The config read can fail (no file, bad TOML); the worker surfaces the
    real error when it starts, so fall back to 0 and let the default budget
    apply. Anything that is not a finite positive number is treated the same
    way: the Engine rejects those values too and uses its own default.
    """
    from protean.domain.config import Config2  # noqa: PLC0415

    try:
        with warnings.catch_warnings():
            # load_from_path warns when no config file is found; the worker
            # reports that, so keep the parent quiet and use the default.
            warnings.simplefilter("ignore")
            config = Config2.load_from_path(_config_search_root(domain_path))
        value = config.get("server", {}).get("drain_timeout", 0)
        if isinstance(value, bool):
            return 0.0
        window = float(value)
    except Exception:  # a bad config falls back to the default budget; logged
        logger.debug(
            "Could not read server.drain_timeout from the project config; "
            "using the default termination budget",
            exc_info=True,
        )
        return 0.0

    return window if math.isfinite(window) and window > 0 else 0.0


def _termination_budget(domain_path: str, floor: float) -> float:
    """How long to wait for a worker to exit before killing it.

    The worker's Engine waits ``[server].drain_timeout`` for in-flight
    handlers before force-cancelling them, so a flat budget would kill a
    worker mid-drain whenever that window is longer. Take the configured
    window plus a margin, never less than ``floor``.
    """
    return max(
        float(floor), _configured_drain_window(domain_path) + _DRAIN_MARGIN_SECONDS
    )


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
        acknowledge_event_store_risk: bool = False,
        log_level: str | None = None,
        log_format: str | None = None,
        log_config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the Supervisor.

        Args:
            domain_path: A ``derive_domain``-compatible string that resolves to
                a Protean Domain (e.g. ``"identity.domain"``).
            num_workers: Number of worker processes to spawn.
            test_mode: If True, each worker Engine runs in test mode
                (limited cycles, then exit).
            debug: Deprecated, removed in v0.20.0. ``True`` is the same as
                ``log_level="DEBUG"``; an explicit ``log_level`` wins.
            acknowledge_event_store_risk: If True, skip the single-writer guard
                and spawn multiple workers even when the domain has event-store
                subscriptions, accepting that their events will be
                double-processed.
            log_level: Log level each worker passes to
                ``Domain.configure_logging()`` in place of ``[logging].level``.
            log_format: Log format each worker passes to
                ``Domain.configure_logging()`` in place of ``[logging].format``.
            log_config: A ``logging.config.dictConfig`` dict. Each worker
                applies it and skips ``Domain.configure_logging()``.

        Raises:
            ValueError: If ``num_workers`` is below 1, or ``log_level`` or
                ``log_format`` is not a value the CLI flags accept.
        """
        if num_workers < 1:
            raise ValueError("num_workers must be >= 1")

        self.domain_path = domain_path
        self.num_workers = num_workers
        self.test_mode = test_mode
        log_level, log_format = _check_log_arguments(log_level, log_format)
        if debug:
            warn_from_registry("supervisor_debug", "Supervisor(debug=...)")
            if log_level is None:
                log_level = "DEBUG"
        self.acknowledge_event_store_risk = acknowledge_event_store_risk
        self.log_level = log_level
        self.log_format = log_format
        self.log_config = log_config

        self.workers: list[BaseProcess] = []
        self.exit_code: int = 0
        self._shutting_down: bool = False
        # Bound in ``run()`` just before workers spawn; ``None`` until then.
        self._shutdown_timeout: float | None = None

        # Log queue plumbing — only populated in multi-worker mode. The queue
        # is created from the spawn context so it is safe to share with child
        # processes; the listener runs on the supervisor and owns the real
        # stream/file handlers.
        self._log_queue: multiprocessing.Queue[logging.LogRecord] | None = None
        self._queue_listener: logging.handlers.QueueListener | None = None

    def run(self) -> None:
        """Spawn workers and block until all have exited.

        Raises:
            ConfigurationError: If ``num_workers > 1`` and the domain has
                event-store subscriptions (unless
                ``acknowledge_event_store_risk`` is True).
        """
        # Defense-in-depth backstop: this runs on every multi-worker start,
        # including ones already pre-checked by the ``protean server`` CLI (which
        # short-circuits before ever constructing a Supervisor when it refuses).
        # On that path this re-derives and re-inits the domain to reach the same
        # "no offenders" conclusion again — redundant but cheap relative to
        # spawning workers, and it's what makes direct ``Supervisor(...).run()``
        # callers (who skip the CLI entirely) safe too. Fail fast before
        # spawning any worker.
        if self.num_workers > 1 and not self.acknowledge_event_store_risk:
            self._guard_event_store_single_writer()

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

        # Bind the shutdown budget to the config as it stands now. The workers
        # read the same config at their own startup, so the two match.
        self._shutdown_timeout = _termination_budget(
            self.domain_path, _SHUTDOWN_TIMEOUT_SECONDS
        )

        # Spawn all workers
        for worker_id in range(self.num_workers):
            process = ctx.Process(
                target=_worker_entry,
                args=(
                    self.domain_path,
                    self.test_mode,
                    worker_id,
                    self._log_queue,
                ),
                kwargs={
                    "log_level": self.log_level,
                    "log_format": self.log_format,
                    "log_config": self.log_config,
                },
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
                # a listener stop failure must not mask the monitor's exit; logged
                except Exception:
                    logger.exception("supervisor.queue_listener_stop_failed")
                self._queue_listener = None

    # ------------------------------------------------------------------
    # Single-writer guard
    # ------------------------------------------------------------------

    def _guard_event_store_single_writer(self) -> None:
        """Refuse multi-worker startup for event-store subscriptions.

        Derives and initializes the domain in the parent process purely to
        resolve subscription types, then closes it again so the parent holds no
        infrastructure connections while the workers run (each worker re-derives
        and re-inits independently in its own interpreter). If any handler
        resolves to an event-store subscription, raises before any worker is
        spawned.

        Any failure to derive or initialize the domain here (unimportable path,
        a module that raises at import, an unreachable database, ...) is *not*
        fatal to the guard: it is swallowed and each worker is left to re-derive
        and report the failure with its own per-worker context, matching the
        pre-guard behavior where derivation happened only inside the workers.
        The guard only ever refuses a start it could positively classify.

        Raises:
            ConfigurationError: If the domain has event-store subscriptions.
        """
        from protean.exceptions import ConfigurationError  # noqa: PLC0415
        from protean.server.subscription import (  # noqa: PLC0415
            event_store_multi_worker_error,
            event_store_subscription_handlers,
        )
        from protean.utils.domain_discovery import derive_domain  # noqa: PLC0415

        try:
            domain = derive_domain(self.domain_path)
            if domain is None:
                # Derivation returned no domain; the workers surface the real
                # error when they re-derive.
                return
            domain.init()
            try:
                offenders = event_store_subscription_handlers(domain)
            finally:
                # Release the parent's transient infrastructure connections;
                # only the workers should hold live connections long-term.
                domain.close()
        except Exception:
            # Could not derive/init the domain to classify it. Defer to the
            # workers rather than crash the parent before any of them start.
            logger.debug(
                "Event-store single-writer guard skipped: domain '%s' could not "
                "be initialized; deferring to workers",
                self.domain_path,
                exc_info=True,
            )
            return

        if offenders:
            raise ConfigurationError(
                event_store_multi_worker_error(offenders, self.num_workers)
            )

    # ------------------------------------------------------------------
    # Signal handling
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """Install signal handlers in the supervisor process."""
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)
        # SIGHUP not available on Windows
        with contextlib.suppress(OSError, AttributeError):
            signal.signal(signal.SIGHUP, self._handle_signal)

    def _handle_signal(self, signum: int, frame: FrameType | None) -> None:
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
        """Send SIGTERM to all workers, wait with timeout, then SIGKILL.

        The timeout is the workers' ``[server].drain_timeout`` plus a margin,
        never less than ``_SHUTDOWN_TIMEOUT_SECONDS``.
        """
        # Send SIGTERM to each living worker
        for worker in self.workers:
            if worker.is_alive() and worker.pid:
                with contextlib.suppress(ProcessLookupError, OSError):
                    os.kill(worker.pid, signal.SIGTERM)

        # Use the budget bound when the workers spawned. Fall back to a fresh
        # read if we shut down before spawning.
        timeout = self._shutdown_timeout
        if timeout is None:
            timeout = _termination_budget(self.domain_path, _SHUTDOWN_TIMEOUT_SECONDS)

        # Workers drain in parallel, so they share one deadline.
        deadline = time.monotonic() + timeout
        for worker in list(self.workers):
            remaining = max(0, deadline - time.monotonic())
            worker.join(timeout=remaining)
            if worker.is_alive():
                logger.warning(
                    "Worker %s did not stop within %gs timeout, killing",
                    worker.name,
                    timeout,
                )
                worker.kill()
                worker.join(timeout=5)
            self.workers.remove(worker)

        logger.info("All workers have been shut down")


def _build_queue_listener(
    queue: "multiprocessing.Queue[logging.LogRecord]",
) -> logging.handlers.QueueListener:
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
    return _WorkerRecordListener(queue, *handlers, respect_handler_level=True)


class _WorkerRecordListener(logging.handlers.QueueListener):
    """A ``QueueListener`` that keeps the ids a worker set on its records.

    The supervisor's handlers carry ``ProteanCorrelationFilter`` and, with
    telemetry on, ``OTelTraceContextFilter``. The listener thread has no
    domain context and no active span, so those filters would overwrite the
    worker's ``correlation_id``, ``causation_id`` and trace ids with empty
    values. This listener tells them to keep the ids already on the record,
    then dispatches through each handler's ``handle()`` as usual.
    """

    def handle(self, record: logging.LogRecord) -> None:
        token = _keep_record_context.set(True)
        try:
            super().handle(record)
        finally:
            _keep_record_context.reset(token)


def _install_worker_log_queue(
    queue: "multiprocessing.Queue[logging.LogRecord]",
) -> None:
    """Install a ``QueueHandler`` as the sole root handler for this worker.

    Called from :func:`_worker_entry` after ``configure_logging()`` so the
    worker's real handlers are replaced by a single ``QueueHandler`` that
    funnels every record to the supervisor's listener.  The Protean filters
    (correlation, trace context, redaction) on the root logger stay there and
    also go on the ``QueueHandler``, so records from child loggers get them
    in the worker, where the domain context is active.

    The root logger and its old handlers can hold redaction filters with
    different keys, for example after ``configure_logging()`` ran twice. The
    ``QueueHandler`` gets every redaction filter whose keys it does not
    already mask, so it masks the union of the keys they held. Redaction
    runs after the correlation and trace-context filters on it.
    """
    root = logging.getLogger()
    # Collected before the swap: once the old handlers are removed, the keys
    # only they held are gone.
    redaction_filters = [
        f
        for target in (root, *root.handlers)
        for f in target.filters
        if isinstance(f, ProteanRedactionFilter)
    ]
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    queue_handler = logging.handlers.QueueHandler(queue)
    root.addHandler(queue_handler)
    for filter_ in list(root.filters):
        if isinstance(filter_, _PROTEAN_ROOT_FILTERS):
            _install_root_filter(filter_)
    for filter_ in redaction_filters:
        _add_redaction_filter_if_uncovered(queue_handler, filter_)
    _move_redaction_filter_last()


def _worker_entry(
    domain_path: str,
    test_mode: bool,
    worker_id: int,
    log_queue: Optional["multiprocessing.Queue[logging.LogRecord]"] = None,
    *,
    log_level: str | None = None,
    log_format: str | None = None,
    log_config: dict[str, Any] | None = None,
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
        worker_id: Numeric identifier for this worker (for logging).
        log_queue: Optional ``multiprocessing.Queue`` for forwarding log
            records to the supervisor's ``QueueListener``.  When ``None``
            (single-worker mode) the worker uses direct handlers from
            ``configure_logging()``.
        log_level: Passed to ``Domain.configure_logging()`` in place of
            ``[logging].level``, as the CLI's ``--log-level`` does. Also the
            level of the bootstrap logging before the domain loads.
        log_format: Passed to ``Domain.configure_logging()`` in place of
            ``[logging].format``, as the CLI's ``--log-format`` does. Also the
            format of the bootstrap logging before the domain loads.
        log_config: A ``dictConfig`` dict, as the CLI's ``--log-config``
            loads. When given, the worker applies it and skips
            ``Domain.configure_logging()``.
    """
    from protean.server.engine import Engine  # noqa: PLC0415
    from protean.utils.domain_discovery import derive_domain  # noqa: PLC0415
    from protean.utils.logging import configure_logging  # noqa: PLC0415

    # A dictConfig from ``--log-config`` replaces ``[logging]`` entirely, as it
    # does in the parent process. It is applied first, before the worker's own
    # logger exists, so its ``disable_existing_loggers`` cannot silence that
    # logger, and no bootstrap handler is left on the root beside it.
    # Otherwise, bootstrap logging the way the parent's CLI callback and
    # ``server`` command do, so the worker has *some* output for derive/init
    # errors at the parent's level and format. With a level or format flag the
    # parent calls ``configure_logging`` with just those, so an unset level
    # resolves through ``PROTEAN_LOG_LEVEL`` and then the ``PROTEAN_ENV`` map.
    # With no flag it uses ``PROTEAN_LOG_LEVEL`` or INFO. The domain's own
    # configuration (which carries ``[logging].redact``, per-logger overrides,
    # etc.) replaces it below.
    if log_config is not None:
        configure_logging(dict_config=log_config)
    elif log_level is None and log_format is None:
        configure_logging(level=os.getenv("PROTEAN_LOG_LEVEL", "INFO"))
    else:
        bootstrap: dict[str, Any] = {}
        if log_level is not None:
            bootstrap["level"] = log_level
        if log_format is not None:
            bootstrap["format"] = log_format
        configure_logging(**bootstrap)

    worker_logger = logging.getLogger(f"protean.server.worker-{worker_id}")
    worker_logger.info(f"Worker {worker_id} (PID {os.getpid()}) starting...")

    try:
        domain = derive_domain(domain_path)
        if domain is None:
            worker_logger.error(
                f"Worker {worker_id}: Failed to derive domain from '{domain_path}'"
            )
            sys.exit(1)

        # Apply domain-level logging config (redact list, per_logger levels,
        # OTel trace context filter when telemetry.enabled is True). This must
        # run BEFORE installing the QueueHandler so we know which handlers the
        # listener should mirror, and so the filters it attaches to root can
        # be copied onto the QueueHandler.
        if log_config is None:
            log_overrides: dict[str, str] = {}
            if log_level is not None:
                log_overrides["level"] = log_level
            if log_format is not None:
                log_overrides["format"] = log_format
            domain.configure_logging(**log_overrides)

        # Multi-worker mode: replace direct handlers with a QueueHandler so
        # records are serialized through the supervisor's listener. Done after
        # domain.configure_logging so we replace its handlers, not the
        # bootstrap ones.
        if log_queue is not None:
            _install_worker_log_queue(log_queue)

        domain.init()

        with domain.domain_context():
            engine = Engine(domain, test_mode=test_mode)
            engine.run()

        sys.exit(engine.exit_code)
    except Exception:  # any worker crash exits with code 1 for the supervisor; logged
        worker_logger.exception(f"Worker {worker_id} failed")
        sys.exit(1)
