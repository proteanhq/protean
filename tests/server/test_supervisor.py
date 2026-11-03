"""Tests for the multi-worker Supervisor.

The Supervisor spawns child processes, so these tests replace the spawn
context and the worker processes with mocks. Everything else, including the
project config, the log queue listener, the monitor loop and the signal
handlers, is real.
"""

import itertools
import json
import logging
import logging.handlers
import os
import queue
import signal
import sys
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from protean._deprecation import RemovedInProtean020Warning
from protean.exceptions import ConfigurationError
from protean.integrations.logging import ProteanRedactionFilter
from protean.server.engine import Engine
from protean.server.reloader import Reloader
from protean.server.supervisor import (
    _DRAIN_MARGIN_SECONDS,
    _MAX_JOIN_SECONDS,
    _SHUTDOWN_TIMEOUT_SECONDS,
    Supervisor,
    _config_search_root,
    _join_within,
    _termination_budget,
    _worker_entry,
)
from tests.shared import change_working_directory_to


@pytest.fixture(autouse=True)
def _restore_signal_handlers():
    """Put back the handlers that ``Supervisor.run()`` and the worker's Engine install."""
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    saved = {sig: signal.getsignal(sig) for sig in signals}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


@pytest.fixture
def project_config(tmp_path, monkeypatch):
    """Write a ``domain.toml`` and return its directory, usable as a domain path."""
    monkeypatch.delenv("DOMAIN_ROOT_PATH", raising=False)
    monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)

    def write(text: str) -> str:
        (tmp_path / "domain.toml").write_text(text)
        return str(tmp_path)

    return write


def _window(value: str) -> str:
    """A ``domain.toml`` whose ``[server].drain_timeout`` is the TOML literal *value*."""
    return f"[server]\ndrain_timeout = {value}\n"


@pytest.fixture
def domain_module(tmp_path, monkeypatch):
    """Write a Python module the worker can load; return its file path.

    Each module gets a unique name, so a module imported by an earlier test
    is never returned from ``sys.modules``.
    """
    monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    names: list[str] = []

    def write(source: str) -> str:
        name = f"worker_domain_{uuid4().hex}"
        names.append(name)
        path = tmp_path / f"{name}.py"
        path.write_text(source)
        return str(path)

    yield write

    for name in names:
        sys.modules.pop(name, None)


@pytest.fixture
def engine_calls(monkeypatch):
    """Record the arguments the worker builds each Engine with, and each
    ``run()`` call, while the real Engine does the work."""
    calls: list[tuple[str, object]] = []
    real_init = Engine.__init__
    real_run = Engine.run

    def init(self, domain, test_mode=False, **kwargs):
        calls.append(("init", {"test_mode": test_mode, **kwargs}))
        real_init(self, domain, test_mode=test_mode, **kwargs)

    def run(self):
        calls.append(("run", None))
        return real_run(self)

    monkeypatch.setattr(Engine, "__init__", init)
    monkeypatch.setattr(Engine, "run", run)
    return calls


def _domain_source(config: dict | None = None) -> str:
    return (
        "from protean import Domain\n\n"
        f"domain = Domain(name='Worker', config={config or {}!r})\n"
    )


def _exited_worker(name: str = "worker-0", pid: int = 12345, exitcode: int = 0):
    """A worker process that has already exited."""
    worker = MagicMock()
    worker.is_alive.return_value = False
    worker.pid = pid
    worker.name = name
    worker.exitcode = exitcode
    return worker


def _stuck_worker():
    """A worker that stays alive through the graceful join."""
    worker = MagicMock()
    worker.is_alive.return_value = True
    worker.pid = 12345
    worker.name = "worker-0"
    worker.join.return_value = None
    return worker


def _spawn_context(on_spawn=None) -> MagicMock:
    """A spawn context whose workers exit as soon as they start.

    The log queue is a real in-process queue, so the supervisor runs a real
    ``QueueListener`` on it. *on_spawn* runs as each worker is created, and
    ``ctx.spawned`` lists the workers created.
    """
    ctx = MagicMock()
    ctx.Queue.side_effect = queue.Queue
    ctx.spawned = []

    def process(**kwargs):
        if on_spawn is not None:
            on_spawn()
        worker = _exited_worker(name=kwargs["name"], pid=4000 + len(ctx.spawned))
        ctx.spawned.append(worker)
        return worker

    ctx.Process.side_effect = process
    return ctx


def _run(supervisor: Supervisor, ctx: MagicMock | None = None) -> MagicMock:
    """Run *supervisor* on a spawn context of exiting workers; return the context.

    ``time.sleep`` is patched so the monitor loop does not wait between polls.
    """
    ctx = ctx if ctx is not None else _spawn_context()
    with (
        patch("multiprocessing.get_context", return_value=ctx),
        patch("time.sleep"),
    ):
        supervisor.run()
    return ctx


def _spawned_kwargs(supervisor: Supervisor) -> list[dict[str, object]]:
    """Run the supervisor and return the keyword arguments of each worker."""
    calls = _run(supervisor).Process.call_args_list
    assert calls
    return [call.kwargs["kwargs"] for call in calls]


class TestSupervisorInit:
    def test_initialization_with_valid_args(self):
        supervisor = Supervisor(
            domain_path="my.domain",
            num_workers=4,
            test_mode=True,
            log_level="DEBUG",
            log_format="json",
            log_config={"version": 1},
        )
        assert supervisor.domain_path == "my.domain"
        assert supervisor.num_workers == 4
        assert supervisor.test_mode is True
        assert supervisor.log_level == "DEBUG"
        assert supervisor.log_format == "json"
        assert supervisor.log_config == {"version": 1}
        assert supervisor.workers == []
        assert supervisor.exit_code == 0
        assert supervisor._shutting_down is False

    @pytest.mark.parametrize("num_workers", [0, -1])
    def test_raises_on_fewer_than_one_worker(self, num_workers):
        with pytest.raises(ValueError, match="num_workers must be >= 1"):
            Supervisor(domain_path="d", num_workers=num_workers)

    def test_defaults(self):
        supervisor = Supervisor(domain_path="d", num_workers=1)
        assert supervisor.test_mode is False
        assert supervisor.log_level is None
        assert supervisor.log_format is None
        assert supervisor.log_config is None


class TestSupervisorSignalHandling:
    def test_install_signal_handlers(self):
        supervisor = Supervisor(domain_path="d", num_workers=1)

        supervisor._install_signal_handlers()

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            assert signal.getsignal(sig) == supervisor._handle_signal

    def test_handle_signal_is_idempotent(self, caplog):
        """The first signal starts the shutdown; a second one is ignored."""
        supervisor = Supervisor(domain_path="d", num_workers=1)
        supervisor.workers = [_exited_worker()]

        with caplog.at_level(logging.INFO, logger="protean.server.supervisor"):
            supervisor._handle_signal(signal.SIGTERM, None)
            supervisor._handle_signal(signal.SIGTERM, None)

        assert supervisor._shutting_down is True
        assert supervisor.workers == []
        messages = [r.getMessage() for r in caplog.records]
        assert messages.count("All workers have been shut down") == 1


class TestSupervisorShutdownWorkers:
    @pytest.mark.parametrize("kill_error", [None, ProcessLookupError])
    def test_sends_sigterm_to_living_workers(self, kill_error):
        """Each living worker gets SIGTERM. A worker that already exited
        (``ProcessLookupError``) does not stop the shutdown."""
        supervisor = Supervisor(domain_path="d", num_workers=2)
        worker1 = _stuck_worker()
        worker2 = _stuck_worker()
        worker2.pid = 12346
        supervisor.workers = [worker1, worker2]

        with patch("os.kill", side_effect=kill_error) as mock_kill:
            supervisor._shutdown_workers()

        assert mock_kill.call_count == 2
        mock_kill.assert_any_call(12345, signal.SIGTERM)
        mock_kill.assert_any_call(12346, signal.SIGTERM)
        assert supervisor.workers == []

    def test_skips_dead_workers(self):
        """Workers that are already dead are not sent signals."""
        supervisor = Supervisor(domain_path="d", num_workers=1)
        supervisor.workers = [_exited_worker()]

        with patch("os.kill") as mock_kill:
            supervisor._shutdown_workers()
            mock_kill.assert_not_called()


class TestSupervisorTerminationBudget:
    """The shutdown budget follows the workers' configured drain window.

    Each worker's Engine waits ``[server].drain_timeout`` for in-flight
    handlers, so a flat 30-second budget would kill a worker mid-drain
    whenever that window is longer.
    """

    @pytest.mark.parametrize(
        "config, budget",
        [
            (_window("45"), 50.0),
            (_window("10"), 30.0),
            (_window("25"), 30.0),
            (_window("26"), 31.0),
            (_window("2_200_000"), 2_200_000 + _DRAIN_MARGIN_SECONDS),
            ("[server]\n", 30.0),
            (_window('"not-a-number"'), 30.0),
            (_window("true"), 30.0),
            (_window("0"), 30.0),
            (_window("-5"), 30.0),
            (_window("nan"), 30.0),
            (_window("inf"), 30.0),
            ("[server\nnot toml", 30.0),
        ],
        ids=[
            "longer-window",
            "default-window",
            "just-under-floor",
            "just-over-floor",
            "long-window-not-capped",
            "window-not-set-uses-the-default",
            "string",
            "boolean",
            "zero",
            "negative",
            "nan",
            "infinity",
            "unreadable-config",
        ],
    )
    def test_budget_is_the_window_plus_margin_never_below_thirty_seconds(
        self, project_config, config, budget
    ):
        domain_path = project_config(config)

        assert _termination_budget(domain_path, _SHUTDOWN_TIMEOUT_SECONDS) == budget

    def test_waits_the_drain_window_plus_margin_before_sigkill(
        self, project_config, caplog
    ):
        """With drain_timeout = 45 the worker gets 45 + margin seconds to exit
        before it is killed, and the warning names that budget. Without a
        budget bound by run(), the config is read at shutdown."""
        supervisor = Supervisor(
            domain_path=project_config(_window("45")), num_workers=1
        )
        assert supervisor._shutdown_timeout is None
        worker = _stuck_worker()
        supervisor.workers = [worker]

        with (
            patch("os.kill"),
            patch("protean.server.supervisor.time.monotonic", return_value=100.0),
            caplog.at_level(logging.WARNING, logger="protean.server.supervisor"),
        ):
            supervisor._shutdown_workers()

        first_join = worker.join.call_args_list[0]
        assert first_join.kwargs["timeout"] == 45 + _DRAIN_MARGIN_SECONDS
        worker.kill.assert_called_once()
        messages = [r.getMessage() for r in caplog.records]
        assert "Worker worker-0 did not stop within 50s timeout, killing" in messages

    @pytest.mark.parametrize("window", ["10", '"not-a-number"'])
    @pytest.mark.parametrize("bound", [True, False])
    def test_default_or_invalid_window_still_waits_thirty_seconds(
        self, project_config, window, bound
    ):
        """The default window of 10, or an invalid one, keeps the 30-second
        wait, whether the budget was bound in run() or is read at shutdown."""
        supervisor = Supervisor(
            domain_path=project_config(_window(window)), num_workers=1
        )
        worker = _stuck_worker()

        if bound:
            _run(supervisor)
        supervisor.workers = [worker]
        with (
            patch("os.kill"),
            patch("protean.server.supervisor.time.monotonic", return_value=100.0),
        ):
            supervisor._shutdown_workers()

        assert worker.join.call_args_list[0].kwargs["timeout"] == 30.0
        worker.kill.assert_called_once()

    def test_run_binds_the_budget_before_spawning(self, project_config):
        """run() binds the budget from the config the workers will read, before
        the first worker starts."""
        supervisor = Supervisor(
            domain_path=project_config(_window("45")), num_workers=1
        )
        budgets_at_spawn = []

        _run(
            supervisor,
            _spawn_context(
                on_spawn=lambda: budgets_at_spawn.append(supervisor._shutdown_timeout)
            ),
        )

        assert budgets_at_spawn == [50.0]

    def test_bound_budget_ignores_a_later_config_change(self, project_config):
        """A config edit after the workers spawned does not shorten the join
        for workers still draining on the window they read at startup."""
        supervisor = Supervisor(domain_path=project_config(_window("2")), num_workers=1)
        supervisor._shutdown_timeout = 50.0
        worker = _stuck_worker()
        supervisor.workers = [worker]

        with (
            patch("os.kill"),
            patch("protean.server.supervisor.time.monotonic", return_value=100.0),
        ):
            supervisor._shutdown_workers()

        assert worker.join.call_args_list[0].kwargs["timeout"] == 50.0


class TestSupervisorReadsTheWorkersConfigFile:
    """The budget comes from the ``domain.toml`` the worker reads, found from
    the domain path the Supervisor was given."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch):
        monkeypatch.delenv("DOMAIN_ROOT_PATH", raising=False)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)

    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        """A scaffold-shaped project: ``src/shop/domain.py`` next to a
        ``domain.toml`` with a 45-second drain window, run from the project
        root, whose ``pyproject.toml`` has no Protean settings."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "shop"\n')
        package = tmp_path / "src" / "shop"
        package.mkdir(parents=True)
        (package / "domain.py").write_text("domain = object()\n")
        (package / "domain.toml").write_text("[server]\ndrain_timeout = 45\n")
        monkeypatch.chdir(tmp_path)
        return package

    @pytest.mark.parametrize(
        "domain_path", ["src/shop/domain.py", "src.shop.domain:domain"]
    )
    def test_join_waits_the_window_from_the_domain_toml(self, project, domain_path):
        supervisor = Supervisor(domain_path=domain_path, num_workers=1)
        worker = _stuck_worker()
        supervisor.workers = [worker]

        with (
            patch("os.kill"),
            patch("protean.server.supervisor.time.monotonic", return_value=100.0),
        ):
            supervisor._shutdown_workers()

        assert worker.join.call_args_list[0].kwargs["timeout"] == 50.0

    def test_dotted_module_on_the_import_path_finds_its_domain_toml(
        self, project, monkeypatch
    ):
        """With ``src`` on ``PYTHONPATH``, ``shop.domain`` imports
        ``src/shop/domain.py``. The budget comes from ``src/shop/domain.toml``,
        not the root ``pyproject.toml``."""
        monkeypatch.syspath_prepend(str(project.parent))
        supervisor = Supervisor(domain_path="shop.domain:domain", num_workers=1)
        worker = _stuck_worker()
        supervisor.workers = [worker]

        with (
            patch("os.kill"),
            patch("protean.server.supervisor.time.monotonic", return_value=100.0),
        ):
            supervisor._shutdown_workers()

        assert worker.join.call_args_list[0].kwargs["timeout"] == 50.0


class TestJoinWithin:
    """``Process.join`` overflows above about 2,147,483 seconds, so a longer
    budget is waited out in bounded joins that add up to the whole window."""

    def test_short_timeout_is_one_join(self):
        process = _stuck_worker()
        _join_within(process, 35.0)
        process.join.assert_called_once_with(timeout=35.0)

    def test_long_timeout_waits_the_full_window_in_bounded_joins(self):
        process = _stuck_worker()
        clock = iter([0.0, _MAX_JOIN_SECONDS, 2 * _MAX_JOIN_SECONDS])
        with patch(
            "protean.server.supervisor.time.monotonic", side_effect=lambda: next(clock)
        ):
            _join_within(process, 2_200_000.0)

        timeouts = [c.kwargs["timeout"] for c in process.join.call_args_list]
        assert timeouts == [_MAX_JOIN_SECONDS, _MAX_JOIN_SECONDS, 200_000.0]

    def test_stops_joining_once_the_process_exits(self):
        process = _stuck_worker()
        process.is_alive.return_value = False
        with patch("protean.server.supervisor.time.monotonic", return_value=0.0):
            _join_within(process, 2_200_000.0)
        process.join.assert_called_once_with(timeout=_MAX_JOIN_SECONDS)


class TestSupervisorSignalDuringSpawn:
    def test_signal_during_spawn_stops_spawning_and_stops_started_workers(
        self, project_config
    ):
        """A signal that lands while workers are spawning stops the loop, and
        the worker started before it is sent SIGTERM rather than left running."""
        supervisor = Supervisor(
            domain_path=project_config(_window("10")), num_workers=3
        )
        started = []

        def spawn(*args, **kwargs):
            process = _stuck_worker()
            process.pid = 4000 + len(started)
            started.append(process)
            # The handler runs as the first worker starts, before it is
            # recorded in ``supervisor.workers``.
            supervisor._handle_signal(signal.SIGTERM, None)
            return process

        ctx = _spawn_context()
        ctx.Process.side_effect = spawn

        with patch("os.kill") as mock_kill:
            _run(supervisor, ctx)

        assert len(started) == 1
        mock_kill.assert_called_once_with(4000, signal.SIGTERM)
        assert supervisor.workers == []


class TestConfigSearchRoot:
    """Where the parent process looks for the ``domain.toml`` its workers read."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch):
        monkeypatch.delenv("DOMAIN_ROOT_PATH", raising=False)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)

    def test_directory_domain_path_is_used_as_is(self, tmp_path):
        assert _config_search_root(str(tmp_path)) == os.path.realpath(str(tmp_path))

    def test_protean_domain_env_overrides_the_argument(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROTEAN_DOMAIN", str(tmp_path))
        assert _config_search_root("my.domain") == os.path.realpath(str(tmp_path))

    def test_working_directory_wins_over_the_import_path(self, tmp_path, monkeypatch):
        """``derive_domain`` puts the working directory first on ``sys.path``,
        so a ``shop`` package there shadows one elsewhere on the path."""
        for root in ("cwd", "lib"):
            package = tmp_path / root / "shop"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("")
            (package / "domain.py").write_text("domain = object()\n")
        monkeypatch.chdir(tmp_path / "cwd")
        monkeypatch.syspath_prepend(str(tmp_path / "lib"))
        assert _config_search_root("shop.domain") == os.path.realpath(
            tmp_path / "cwd" / "shop"
        )

    def test_submodule_of_a_plain_module_falls_back_to_cwd(self, tmp_path, monkeypatch):
        (tmp_path / "shop.py").write_text("")
        monkeypatch.chdir(tmp_path)
        assert _config_search_root("shop.domain") == os.getcwd()

    def test_namespace_package_falls_back_to_cwd(self, tmp_path, monkeypatch):
        """A namespace package has no file to anchor the worker's root."""
        (tmp_path / "src" / "shop").mkdir(parents=True)
        monkeypatch.chdir(tmp_path)
        assert _config_search_root("src.shop") == os.getcwd()

    def test_package_init_is_not_executed(self, tmp_path, monkeypatch):
        package = tmp_path / "shop"
        package.mkdir()
        (package / "__init__.py").write_text("raise RuntimeError('imported')\n")
        (package / "domain.py").write_text("domain = object()\n")
        monkeypatch.chdir(tmp_path)
        assert _config_search_root("shop.domain") == os.path.realpath(package)


class TestSupervisorMonitor:
    @pytest.mark.parametrize(
        "exitcode, exit_code, message",
        [
            (0, 0, "Worker worker-0 exited cleanly"),
            (1, 1, "Worker worker-0 (PID 12345) exited with code 1"),
        ],
        ids=["clean-exit", "crash"],
    )
    def test_monitor_reaps_exited_worker(self, caplog, exitcode, exit_code, message):
        """The monitor removes an exited worker. A non-zero exit code sets the
        supervisor's exit code to 1."""
        supervisor = Supervisor(domain_path="d", num_workers=1)
        supervisor.workers = [_exited_worker(exitcode=exitcode)]

        with (
            patch("time.sleep"),
            caplog.at_level(logging.INFO, logger="protean.server.supervisor"),
        ):
            supervisor._monitor()

        assert supervisor.workers == []
        assert supervisor.exit_code == exit_code
        assert message in [r.getMessage() for r in caplog.records]

    def test_monitor_handles_keyboard_interrupt(self, caplog):
        """Monitor catches KeyboardInterrupt and shuts the workers down."""
        supervisor = Supervisor(domain_path="d", num_workers=1)
        worker = _exited_worker()
        worker.is_alive.side_effect = itertools.chain(
            [KeyboardInterrupt], itertools.repeat(False)
        )
        supervisor.workers = [worker]

        with caplog.at_level(logging.INFO, logger="protean.server.supervisor"):
            supervisor._monitor()

        assert supervisor._shutting_down is True
        assert supervisor.workers == []
        # Each shutdown ends with this record, so one record means one shutdown.
        assert [r.getMessage() for r in caplog.records].count(
            "All workers have been shut down"
        ) == 1


class TestSupervisorMonitorEdgeCases:
    def test_monitor_exits_when_shutting_down_flag_set(self):
        """Monitor loop stops when _shutting_down is True."""
        supervisor = Supervisor(domain_path="d", num_workers=1)
        supervisor._shutting_down = True

        mock_worker = MagicMock()
        mock_worker.is_alive.return_value = True
        mock_worker.name = "worker-0"
        mock_worker.pid = 12345
        supervisor.workers = [mock_worker]

        # Monitor should exit immediately because _shutting_down is True
        supervisor._monitor()

        # Worker should be joined during final cleanup
        mock_worker.join.assert_called_once_with(timeout=5)
        assert len(supervisor.workers) == 0

    def test_monitor_final_cleanup_joins_remaining_workers(self):
        """After the main loop, monitor joins any remaining workers."""
        supervisor = Supervisor(domain_path="d", num_workers=1)

        call_count = [0]

        def alive_then_dead():
            call_count[0] += 1
            # First call in the loop: worker is alive; subsequent calls: dead
            return call_count[0] <= 1

        mock_worker = MagicMock()
        mock_worker.is_alive.side_effect = alive_then_dead
        mock_worker.exitcode = 0
        mock_worker.name = "worker-0"
        mock_worker.pid = 12345

        supervisor.workers = [mock_worker]

        # Trigger shutdown after one iteration via sleep side-effect
        def set_shutdown(*args):
            supervisor._shutting_down = True

        with patch("time.sleep", side_effect=set_shutdown):
            supervisor._monitor()

        assert len(supervisor.workers) == 0


class TestSupervisorRun:
    def test_run_spawns_workers_and_monitors(self):
        """run() installs the signal handlers, spawns and starts every worker,
        and monitors them until they exit."""
        supervisor = Supervisor(domain_path="d", num_workers=2)

        ctx = _run(supervisor)

        assert ctx.Process.call_count == 2
        assert [worker.start.call_count for worker in ctx.spawned] == [1, 1]
        assert supervisor.workers == []
        assert supervisor.exit_code == 0
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            assert signal.getsignal(sig) == supervisor._handle_signal

    def test_run_passes_correct_args_to_worker_entry(self):
        """run() passes correct arguments to _worker_entry. A single worker
        logs directly, so no log queue or listener is created."""
        supervisor = Supervisor(
            domain_path="my.domain",
            num_workers=1,
            test_mode=True,
            log_level="DEBUG",
            log_format="json",
        )

        ctx = _run(supervisor)

        ctx.Process.assert_called_once_with(
            target=_worker_entry,
            args=("my.domain", True, 0, None),
            kwargs={"log_level": "DEBUG", "log_format": "json", "log_config": None},
            name="protean-worker-0",
        )
        ctx.Queue.assert_not_called()
        assert supervisor._log_queue is None
        assert supervisor._queue_listener is None


class TestSupervisorEventStoreGuard:
    """The Supervisor is a documented programmatic entry point, so it enforces
    the single-writer boundary itself (defense-in-depth) rather than relying on
    the CLI guard."""

    @pytest.fixture(autouse=True)
    def reset_path(self):
        """Restore sys.path and cwd after tests that chdir into a fixture."""
        original_path = sys.path[:]
        cwd = Path.cwd()

        yield

        sys.path[:] = original_path
        os.chdir(cwd)

    def test_run_refuses_event_store_domain(self):
        """run() raises before spawning when the domain has event-store subs."""
        change_working_directory_to("test31")

        supervisor = Supervisor(domain_path="event_store_domain.py", num_workers=2)

        with patch("multiprocessing.get_context") as mock_get_context:
            with pytest.raises(ConfigurationError, match="event-store"):
                supervisor.run()

            # Guard fires before any worker machinery is set up.
            mock_get_context.assert_not_called()

    def test_run_names_offending_handler(self):
        """The raised error names the offending handler and the override."""
        change_working_directory_to("test31")

        supervisor = Supervisor(domain_path="event_store_domain.py", num_workers=2)

        with pytest.raises(ConfigurationError) as exc_info:
            supervisor.run()

        message = str(exc_info.value)
        assert "OrderEventHandler" in message
        assert "acknowledge_event_store_risk=True" in message

    @pytest.mark.parametrize(
        "domain_path, num_workers, acknowledge",
        [
            ("event_store_domain.py", 2, True),
            ("stream_domain.py", 2, False),
            ("event_store_domain.py", 1, False),
        ],
        ids=["acknowledged-risk", "stream-subscriptions", "single-worker"],
    )
    def test_run_spawns_workers_when_the_guard_passes(
        self, domain_path, num_workers, acknowledge
    ):
        """The guard lets the start proceed when the risk is acknowledged, when
        every handler resolves to a stream subscription, and for one worker."""
        change_working_directory_to("test31")

        supervisor = Supervisor(
            domain_path=domain_path,
            num_workers=num_workers,
            acknowledge_event_store_risk=acknowledge,
        )

        ctx = _run(supervisor)

        assert ctx.Process.call_count == num_workers

    @pytest.mark.parametrize(
        "source",
        [
            None,
            "raise RuntimeError('import blew up')\n",
            _domain_source({"databases": {"default": {"provider": "nope"}}}),
        ],
        ids=["unimportable", "raises-on-import", "fails-to-init"],
    )
    def test_guard_defers_a_domain_it_cannot_load_to_the_workers(
        self, domain_module, caplog, source
    ):
        """A domain that cannot be imported, raises at import, or fails in
        ``init()`` (for example, an unknown database) does not crash the
        parent before any worker spawns. Each worker re-derives the domain and
        reports the failure."""
        domain_path = "does.not.exist" if source is None else domain_module(source)
        supervisor = Supervisor(domain_path=domain_path, num_workers=2)

        with caplog.at_level(logging.DEBUG, logger="protean.server.supervisor"):
            supervisor._guard_event_store_single_writer()

        skipped = [
            r
            for r in caplog.records
            if r.getMessage().startswith("Event-store single-writer guard skipped")
        ]
        assert len(skipped) == 1

    def test_guard_tolerates_domain_less_module(self, tmp_path, monkeypatch, caplog):
        """When no domain is found, the guard leaves it for the worker to report."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
        monkeypatch.delitem(sys.modules, "domain", raising=False)
        supervisor = Supervisor(domain_path="", num_workers=2)

        with caplog.at_level(logging.DEBUG, logger="protean.server.supervisor"):
            supervisor._guard_event_store_single_writer()

        assert caplog.records == []


# A worker domain module with no domain. When the worker imports it, it
# records the root logger's state at that moment next to the module file.
_PROBE_SOURCE = """\
import json
import logging
import pathlib

_root = logging.getLogger()
_record = logging.LogRecord("probe", logging.WARNING, "", 0, "probe-line", (), None)
pathlib.Path(__file__).with_suffix(".json").write_text(
    json.dumps(
        {
            "level": _root.level,
            "handlers": len(_root.handlers),
            "lines": [handler.format(_record) for handler in _root.handlers],
        }
    )
)
"""


def _probe(domain_module, target=_worker_entry, args=None, kwargs=None) -> dict:
    """Run the worker entry on a probe module; return the root logger state
    when the worker loaded the domain.

    The probe has no domain, so the worker exits with code 1 right after.
    """
    path = domain_module(_PROBE_SOURCE)
    args = (path, False, 0) if args is None else (path, *args[1:])
    with pytest.raises(SystemExit, match="1"):
        target(*args, **(kwargs or {}))
    return json.loads(Path(path).with_suffix(".json").read_text())


def _renders_json(state: dict) -> bool:
    """True when a root handler rendered the probe record as JSON."""
    for line in state["lines"]:
        try:
            if json.loads(line).get("event") == "probe-line":
                return True
        except ValueError:
            continue
    return False


def _redaction_keys() -> list[set[str]]:
    root = logging.getLogger()
    return [f._keys for f in root.filters if isinstance(f, ProteanRedactionFilter)]


class TestWorkerEntry:
    def test_worker_entry_success(self, domain_module, engine_calls):
        """_worker_entry loads and initializes the domain, applies its logging
        table, and runs the engine to a clean exit."""
        path = domain_module(_domain_source({"logging": {"redact": ["secret"]}}))

        with pytest.raises(SystemExit, match="0"):
            _worker_entry(path, test_mode=True, worker_id=0)

        assert engine_calls == [("init", {"test_mode": True}), ("run", None)]

        keys = _redaction_keys()
        assert len(keys) == 1
        assert "secret" in keys[0]

    def test_worker_entry_domain_derivation_failure(self, tmp_path, monkeypatch):
        """_worker_entry exits with code 1 when no domain is found."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
        monkeypatch.delitem(sys.modules, "domain", raising=False)

        with pytest.raises(SystemExit, match="1"):
            _worker_entry("", test_mode=False, worker_id=0)


class TestWorkerEntryBootstrapLevel:
    """Before the domain loads, the worker logs at the parent's level."""

    @pytest.mark.parametrize("value", ["DEBUG", "debug"])
    def test_protean_log_level_sets_the_bootstrap_level(
        self, domain_module, monkeypatch, value
    ):
        monkeypatch.setenv("PROTEAN_LOG_LEVEL", value)

        assert _probe(domain_module)["level"] == logging.DEBUG

    def test_log_level_flag_wins_over_protean_log_level(
        self, domain_module, monkeypatch
    ):
        monkeypatch.setenv("PROTEAN_LOG_LEVEL", "DEBUG")

        state = _probe(domain_module, kwargs={"log_level": "ERROR"})

        assert state["level"] == logging.ERROR

    def test_defaults_to_info_under_development_env(self, domain_module, monkeypatch):
        # The PROTEAN_ENV map would pick DEBUG here. With no logging flag, the
        # parent bootstraps at INFO, so the worker does too.
        monkeypatch.delenv("PROTEAN_LOG_LEVEL", raising=False)
        monkeypatch.setenv("PROTEAN_ENV", "development")

        assert _probe(domain_module)["level"] == logging.INFO

    def test_log_format_alone_resolves_the_level_like_the_parent(
        self, domain_module, monkeypatch
    ):
        # With only --log-format, the parent leaves the level to
        # PROTEAN_LOG_LEVEL and then the PROTEAN_ENV map.
        monkeypatch.delenv("PROTEAN_LOG_LEVEL", raising=False)
        monkeypatch.setenv("PROTEAN_ENV", "development")

        state = _probe(domain_module, kwargs={"log_format": "json"})

        assert state["level"] == logging.DEBUG
        assert _renders_json(state)

    def test_log_level_and_format_both_reach_the_bootstrap(self, domain_module):
        state = _probe(
            domain_module, kwargs={"log_level": "ERROR", "log_format": "json"}
        )

        assert state["level"] == logging.ERROR
        assert _renders_json(state)

    def test_protean_log_level_does_not_override_log_config(
        self, domain_module, monkeypatch
    ):
        monkeypatch.setenv("PROTEAN_LOG_LEVEL", "DEBUG")
        dict_config = {"version": 1, "root": {"level": "ERROR"}}

        state = _probe(domain_module, kwargs={"log_config": dict_config})

        assert state["level"] == logging.ERROR

    def test_reload_worker_uses_protean_log_level(self, domain_module, monkeypatch):
        monkeypatch.setenv("PROTEAN_LOG_LEVEL", "DEBUG")
        reloader = Reloader(domain_path="d")
        reloader._ctx = MagicMock()

        reloader._start_process()

        call = reloader._ctx.Process.call_args
        state = _probe(
            domain_module,
            target=call.kwargs["target"],
            args=call.kwargs["args"],
            kwargs=call.kwargs["kwargs"],
        )

        assert state["level"] == logging.DEBUG


class TestWorkerEntryLoggingFlags:
    """The worker applies the CLI logging flags the way the parent does."""

    def test_log_level_overrides_logging_table_and_keeps_redaction(self, domain_module):
        path = domain_module(
            _domain_source({"logging": {"level": "INFO", "redact": ["secret"]}})
        )

        with pytest.raises(SystemExit, match="0"):
            _worker_entry(path, True, 0, log_level="DEBUG")

        assert logging.getLogger().level == logging.DEBUG
        keys = _redaction_keys()
        assert len(keys) == 1
        assert "secret" in keys[0]

    @pytest.mark.parametrize(
        "flags, level",
        [
            ({"log_format": "json"}, logging.INFO),
            ({"log_level": "WARNING", "log_format": "json"}, logging.WARNING),
        ],
        ids=["format-alone", "level-and-format"],
    )
    def test_log_format_overrides_the_logging_table(self, domain_module, flags, level):
        """``log_format`` switches the domain's logging to JSON. A ``log_level``
        given with it overrides the table's level too."""
        path = domain_module(_domain_source({"logging": {"level": "INFO"}}))

        with pytest.raises(SystemExit, match="0"):
            _worker_entry(path, True, 0, **flags)

        root = logging.getLogger()
        assert root.level == level
        record = logging.LogRecord(
            "probe", logging.WARNING, "", 0, "probe-line", (), None
        )
        lines = [handler.format(record) for handler in root.handlers]
        assert _renders_json({"lines": lines})

    def test_log_config_is_applied_and_logging_table_is_skipped(self, domain_module):
        path = domain_module(
            _domain_source({"logging": {"level": "DEBUG", "redact": ["secret"]}})
        )
        log_config = {
            "version": 1,
            "handlers": {"null": {"class": "logging.NullHandler"}},
            "root": {"level": "WARNING", "handlers": ["null"]},
        }

        with pytest.raises(SystemExit, match="0"):
            _worker_entry(path, True, 0, log_config=log_config)

        assert logging.getLogger().level == logging.WARNING
        assert _redaction_keys() == []

    def test_empty_log_config_is_rejected_by_dict_config(self, domain_module):
        """An empty ``log_config`` has no ``version`` key, so ``dictConfig``
        rejects it before the worker loads the domain."""
        path = domain_module(_domain_source())

        with pytest.raises(ValueError, match="version"):
            _worker_entry(path, True, 0, log_config={})

    @pytest.mark.parametrize(
        "log_config", [None, {"version": 1}], ids=["no-log-config", "log-config"]
    )
    def test_log_queue_makes_the_queue_handler_the_only_root_handler(
        self, domain_module, log_config
    ):
        path = domain_module(_domain_source())
        log_queue: queue.Queue = queue.Queue()

        with pytest.raises(SystemExit, match="0"):
            _worker_entry(path, True, 0, log_queue, log_config=log_config)

        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        assert isinstance(handlers[0], logging.handlers.QueueHandler)
        assert handlers[0].queue is log_queue

    def test_engine_is_built_without_debug(self, domain_module, engine_calls):
        """``log_level="DEBUG"`` sets the logging level only. The engine is not
        built in debug mode, so its own logger keeps its level unset."""
        engine_logger = logging.getLogger("protean.server.engine")
        assert engine_logger.level == logging.NOTSET
        path = domain_module(_domain_source())

        with pytest.raises(SystemExit, match="0"):
            _worker_entry(path, True, 0, log_level="DEBUG")

        assert engine_calls == [("init", {"test_mode": True}), ("run", None)]
        assert engine_logger.level == logging.NOTSET

    def test_log_config_does_not_silence_the_worker_failure_message(
        self, domain_module
    ):
        records: list[logging.LogRecord] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        # No ``disable_existing_loggers`` key, so dictConfig disables every
        # logger that exists when it runs.
        log_config = {
            "version": 1,
            "handlers": {"capture": {"()": _ListHandler}},
            "root": {"level": "INFO", "handlers": ["capture"]},
        }
        path = domain_module(
            _domain_source({"databases": {"default": {"provider": "nope"}}})
        )

        with pytest.raises(SystemExit, match="1"):
            _worker_entry(path, False, 41, log_config=log_config)

        assert logging.getLogger("protean.server.worker-41").disabled is False
        failures = [r for r in records if r.getMessage() == "Worker 41 failed"]
        assert len(failures) == 1
        assert failures[0].exc_info is not None
        assert isinstance(failures[0].exc_info[1], ConfigurationError)
        assert "nope" in str(failures[0].exc_info[1])

    def test_log_config_without_root_leaves_no_bootstrap_handler(self, domain_module):
        # A spawned worker starts with no root handlers.
        logging.getLogger().handlers = []

        state = _probe(
            domain_module,
            kwargs={"log_config": {"version": 1, "disable_existing_loggers": False}},
        )

        assert state["handlers"] == 0


class TestLoggingArgumentValidation:
    @pytest.mark.parametrize(
        "log_level, log_format, expected_level, expected_format",
        [("debug", "json", "DEBUG", "json"), ("", "", None, None)],
        ids=["upper-cased", "empty-is-not-given"],
    )
    def test_logging_arguments_are_normalised(
        self, log_level, log_format, expected_level, expected_format
    ):
        """The level is upper-cased, and empty values count as not given."""
        supervisor = Supervisor(
            domain_path="d", num_workers=1, log_level=log_level, log_format=log_format
        )

        assert supervisor.log_level == expected_level
        assert supervisor.log_format == expected_format

    def test_empty_log_level_does_not_hide_debug(self):
        with pytest.warns(RemovedInProtean020Warning):
            supervisor = Supervisor(
                domain_path="d", num_workers=1, debug=True, log_level=""
            )

        assert supervisor.log_level == "DEBUG"


class TestSupervisorLoggingArguments:
    def test_logging_arguments_reach_every_worker(self):
        supervisor = Supervisor(
            domain_path="d",
            num_workers=2,
            log_level="DEBUG",
            log_format="json",
            log_config={"version": 1},
            acknowledge_event_store_risk=True,
        )

        spawned = _spawned_kwargs(supervisor)

        assert len(spawned) == 2
        for kwargs in spawned:
            assert kwargs == {
                "log_level": "DEBUG",
                "log_format": "json",
                "log_config": {"version": 1},
            }


class TestSupervisorDebugDeprecation:
    def test_debug_true_warns_and_maps_to_debug_level(self):
        with pytest.warns(RemovedInProtean020Warning, match="v0.20.0") as record:
            supervisor = Supervisor(domain_path="d", num_workers=1, debug=True)

        assert len(record) == 1
        assert "Supervisor(debug=...)" in str(record[0].message)
        assert 'log_level="DEBUG"' in str(record[0].message)
        assert record[0].filename == __file__
        assert _spawned_kwargs(supervisor)[0]["log_level"] == "DEBUG"

    def test_explicit_log_level_wins_over_debug(self):
        with pytest.warns(RemovedInProtean020Warning):
            supervisor = Supervisor(
                domain_path="d", num_workers=1, debug=True, log_level="WARNING"
            )

        assert _spawned_kwargs(supervisor)[0]["log_level"] == "WARNING"

    @pytest.mark.parametrize("kwargs", [{"debug": False}, {}], ids=["false", "omitted"])
    def test_debug_false_or_omitted_does_not_warn(self, kwargs):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            supervisor = Supervisor(domain_path="d", num_workers=1, **kwargs)

        assert caught == []
        assert supervisor.log_level is None
