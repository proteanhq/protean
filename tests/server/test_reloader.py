"""Tests for the development Reloader.

The Reloader spawns child processes and watches files, so these tests replace
the spawn context, the worker processes and the ``watchfiles`` watcher with
mocks. The project config, the signal handlers and the reloader's own
lifecycle are real.
"""

import logging
import os
import signal
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from watchfiles import PythonFilter

from protean._deprecation import RemovedInProtean020Warning
from protean.server.reloader import (
    _EXTRA_IGNORE_DIRS,
    _SHUTDOWN_TIMEOUT_SECONDS,
    Reloader,
    _display_path,
)
from protean.server.supervisor import _DRAIN_MARGIN_SECONDS, _worker_entry


@pytest.fixture(autouse=True)
def _restore_signal_handlers():
    """Put back the handlers that ``Reloader.run()`` installs."""
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


def _exited_process(exitcode: int = 0) -> MagicMock:
    """A worker process that has already exited."""
    process = MagicMock()
    process.is_alive.return_value = False
    process.pid = 1234
    process.exitcode = exitcode
    return process


def _stopping_process() -> MagicMock:
    """A worker that is alive until it is joined."""
    process = MagicMock()
    # ``is_alive`` reports True before the join (to trigger SIGTERM) and
    # False after, so the kill fallback does not fire.
    process.is_alive.side_effect = iter([True, False, False])
    process.pid = 1234
    process.exitcode = 0
    return process


def _spawn_context() -> MagicMock:
    """A spawn context whose workers exit as soon as they are stopped."""
    ctx = MagicMock()
    ctx.Process.side_effect = lambda **kwargs: _exited_process()
    return ctx


class TestReloaderInit:
    @pytest.mark.parametrize(
        "kwargs", [{}, {"reload_dirs": []}], ids=["omitted", "empty"]
    )
    def test_initialization_with_defaults(self, kwargs):
        reloader = Reloader(domain_path="my.domain", **kwargs)

        assert reloader.domain_path == "my.domain"
        assert reloader.test_mode is False
        assert reloader.log_level is None
        assert reloader.log_format is None
        assert reloader.log_config is None
        assert reloader.reload_dirs == [Path.cwd().resolve()]
        assert reloader.exit_code == 0
        assert reloader.process is None
        assert reloader._shutting_down is False
        assert reloader.should_exit.is_set() is False

    def test_initialization_with_explicit_args(self, tmp_path):
        """``reload_dirs`` accepts strings and ``Path`` objects and resolves each."""
        sub = tmp_path / "src"
        sub.mkdir()

        reloader = Reloader(
            domain_path="svc.domain",
            reload_dirs=[str(sub), tmp_path / "nested"],
            test_mode=True,
            log_level="DEBUG",
            log_format="json",
            log_config={"version": 1},
        )

        assert reloader.domain_path == "svc.domain"
        assert reloader.test_mode is True
        assert reloader.log_level == "DEBUG"
        assert reloader.log_format == "json"
        assert reloader.log_config == {"version": 1}
        assert reloader.reload_dirs == [sub.resolve(), (tmp_path / "nested").resolve()]


class TestReloaderProcessLifecycle:
    def test_start_process_spawns_worker_with_correct_args(self):
        reloader = Reloader(
            domain_path="my.domain",
            test_mode=True,
            log_level="DEBUG",
            log_format="json",
            log_config={"version": 1},
        )

        mock_process = MagicMock()
        mock_process.pid = 4242
        reloader._ctx = MagicMock()
        reloader._ctx.Process.return_value = mock_process

        reloader._start_process()

        reloader._ctx.Process.assert_called_once_with(
            target=_worker_entry,
            args=("my.domain", True, 0, None),
            kwargs={
                "log_level": "DEBUG",
                "log_format": "json",
                "log_config": {"version": 1},
            },
            name="protean-reload-worker",
        )
        mock_process.start.assert_called_once()
        assert reloader.process is mock_process

    @pytest.mark.parametrize("kill_error", [None, ProcessLookupError])
    def test_stop_process_sends_sigterm_and_joins(self, kill_error):
        """The worker gets SIGTERM and is joined. A worker that already exited
        (``ProcessLookupError``) does not stop the shutdown."""
        reloader = Reloader(domain_path="my.domain")
        mock_process = _stopping_process()
        reloader.process = mock_process

        with patch("os.kill", side_effect=kill_error) as mock_kill:
            reloader._stop_process()

        mock_kill.assert_called_once_with(1234, signal.SIGTERM)
        mock_process.join.assert_called_once()
        mock_process.kill.assert_not_called()
        assert reloader.process is None

    def test_stop_process_is_noop_when_no_process(self):
        reloader = Reloader(domain_path="my.domain")
        # No process attached, so this must not raise.
        reloader._stop_process()
        assert reloader.process is None

    def test_stop_process_kills_when_timeout_exceeded(self):
        reloader = Reloader(domain_path="my.domain")

        mock_process = MagicMock()
        mock_process.is_alive.return_value = True
        mock_process.pid = 1234
        mock_process.exitcode = None
        reloader.process = mock_process

        with patch("os.kill"):
            reloader._stop_process()

        mock_process.kill.assert_called_once()

    def test_restart_process_stops_then_starts(self):
        """A restart replaces the worker and clears the previous exit code."""
        reloader = Reloader(domain_path="my.domain")
        reloader._ctx = _spawn_context()
        old_process = _exited_process(exitcode=7)
        reloader.process = old_process

        reloader._restart_process()

        old_process.join.assert_called()
        reloader._ctx.Process.assert_called_once()
        assert reloader.process is not old_process
        reloader.process.start.assert_called_once()
        assert reloader.exit_code == 0

    def test_restart_process_does_not_start_when_exiting(self):
        reloader = Reloader(domain_path="my.domain")
        reloader._ctx = _spawn_context()
        reloader.process = _exited_process()
        reloader.should_exit.set()

        reloader._restart_process()

        reloader._ctx.Process.assert_not_called()
        assert reloader.process is None

    def test_logging_arguments_survive_a_restart(self):
        reloader = Reloader(domain_path="d", log_format="json")
        reloader._ctx = _spawn_context()

        reloader._start_process()
        reloader._restart_process()

        calls = reloader._ctx.Process.call_args_list
        assert len(calls) == 2
        for call in calls:
            assert call.kwargs["kwargs"]["log_format"] == "json"


class TestReloaderTerminationBudget:
    """The join budget follows the Engine's configured drain window.

    The worker waits ``[server].drain_timeout`` for in-flight handlers before
    force-cancelling them, so a flat 10-second join would kill it mid-drain
    whenever that window is longer.
    """

    @pytest.mark.parametrize(
        "config, budget",
        [
            (_window("20"), 20 + _DRAIN_MARGIN_SECONDS),
            (_window("2"), float(_SHUTDOWN_TIMEOUT_SECONDS)),
            (_window('"not-a-number"'), float(_SHUTDOWN_TIMEOUT_SECONDS)),
            (_window("true"), float(_SHUTDOWN_TIMEOUT_SECONDS)),
            (_window("0"), float(_SHUTDOWN_TIMEOUT_SECONDS)),
            (_window("-5"), float(_SHUTDOWN_TIMEOUT_SECONDS)),
            (_window("nan"), float(_SHUTDOWN_TIMEOUT_SECONDS)),
            (_window("inf"), float(_SHUTDOWN_TIMEOUT_SECONDS)),
            ("[server\nnot toml", float(_SHUTDOWN_TIMEOUT_SECONDS)),
            ("[server]\n", 10 + _DRAIN_MARGIN_SECONDS),
        ],
        ids=[
            "longer-window",
            "short-window",
            "string",
            "boolean",
            "zero",
            "negative",
            "nan",
            "infinity",
            "unreadable-config",
            "missing-window",
        ],
    )
    def test_budget_is_the_window_plus_margin_never_below_the_default(
        self, project_config, config, budget
    ):
        """A short window does not shorten the budget below 10 seconds, and
        values the Engine rejects do not stretch or shrink it. A config that
        does not read here falls back too; the worker surfaces the real error.
        A config with no window gets the Engine's default 10-second window."""
        reloader = Reloader(domain_path=project_config(config))

        assert reloader._termination_timeout() == budget

    def test_budget_refreshes_between_worker_generations(self, project_config):
        """A domain.toml change between restarts binds the new window to the
        replacement worker, not the value read when the reloader started."""
        reloader = Reloader(domain_path=project_config(_window("20")))
        reloader._ctx = MagicMock()

        reloader._start_process()
        assert reloader._stop_timeout == 20 + _DRAIN_MARGIN_SECONDS

        project_config(_window("40"))
        reloader._start_process()
        assert reloader._stop_timeout == 40 + _DRAIN_MARGIN_SECONDS

    def test_stop_process_joins_for_the_bound_budget(self):
        """The join uses the budget bound when the worker started, so a 20s
        drain is not cut at 10 and a later config edit cannot shorten it."""
        reloader = Reloader(domain_path="my.domain")
        reloader._stop_timeout = 20 + _DRAIN_MARGIN_SECONDS
        mock_process = _stopping_process()
        reloader.process = mock_process

        with patch("os.kill"):
            reloader._stop_process()

        mock_process.join.assert_called_once_with(timeout=20 + _DRAIN_MARGIN_SECONDS)
        mock_process.kill.assert_not_called()


class TestReloaderConfigSearchRoot:
    """Where the reloader parent looks for the project config, so its join
    budget is sized from the same ``domain.toml`` the worker reads."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch):
        monkeypatch.delenv("DOMAIN_ROOT_PATH", raising=False)
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)

    def test_domain_file_path_resolves_to_its_directory(self, tmp_path):
        """A file-path domain reads config from the file's directory, matching
        the worker's ``Domain.root_path`` even when the CWD differs."""
        domain_file = tmp_path / "domain.py"
        domain_file.write_text("domain = object()\n")
        reloader = Reloader(domain_path=str(domain_file))
        assert reloader._config_search_root() == os.path.realpath(str(tmp_path))

    def test_domain_path_without_extension_finds_the_py_file(self, tmp_path):
        """``--domain path/to/domain`` (no ``.py``) resolves to that directory."""
        (tmp_path / "domain.py").write_text("domain = object()\n")
        reloader = Reloader(domain_path=str(tmp_path / "domain"))
        assert reloader._config_search_root() == os.path.realpath(str(tmp_path))

    def test_factory_suffix_is_stripped(self, tmp_path):
        """A ``path:factory`` domain resolves on the path, ignoring the suffix."""
        domain_file = tmp_path / "app.py"
        domain_file.write_text("def create():\n    return object()\n")
        reloader = Reloader(domain_path=f"{domain_file}:create")
        assert reloader._config_search_root() == os.path.realpath(str(tmp_path))

    def test_domain_root_path_env_wins(self, tmp_path, monkeypatch):
        """``DOMAIN_ROOT_PATH`` overrides, exactly as the worker's Domain honours
        it."""
        monkeypatch.setenv("DOMAIN_ROOT_PATH", str(tmp_path))
        reloader = Reloader(domain_path="some/other/domain.py")
        assert reloader._config_search_root() == str(tmp_path)

    def test_dotted_module_resolves_under_cwd(self, tmp_path, monkeypatch):
        """``src.shop.domain`` is the scaffolded Dockerfile's ``--domain``. It
        resolves to ``src/shop`` under the working directory, where the
        scaffold puts ``domain.toml``."""
        package = tmp_path / "src" / "shop"
        package.mkdir(parents=True)
        (package / "domain.py").write_text("domain = object()\n")
        monkeypatch.chdir(tmp_path)
        reloader = Reloader(domain_path="src.shop.domain:domain")
        assert reloader._config_search_root() == os.path.realpath(package)

    def test_unresolvable_dotted_module_falls_back_to_cwd(self):
        """A dotted module with no matching file under the working directory
        uses the working directory, where ``domain.toml`` conventionally
        lives."""
        reloader = Reloader(domain_path="my.package.domain")
        assert reloader._config_search_root() == os.getcwd()


class TestReloaderSignalHandling:
    def test_install_signal_handlers(self):
        reloader = Reloader(domain_path="my.domain")

        reloader._install_signal_handlers()

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            assert signal.getsignal(sig) == reloader._handle_signal

    def test_handle_signal_is_idempotent(self, caplog):
        """The first signal requests the exit; a second one is ignored."""
        reloader = Reloader(domain_path="my.domain")

        with caplog.at_level(logging.INFO, logger="protean.server.reloader"):
            reloader._handle_signal(signal.SIGTERM, None)
            reloader._handle_signal(signal.SIGINT, None)

        assert reloader._shutting_down is True
        assert reloader.should_exit.is_set() is True
        received = [
            r.getMessage()
            for r in caplog.records
            if r.getMessage().startswith("Reloader received")
        ]
        assert received == ["Reloader received SIGTERM, shutting down"]


def _run(reloader: Reloader, changes=None, watch_side_effect=None) -> MagicMock:
    """Run *reloader* on a mocked spawn context with a fake watcher.

    The watcher yields each change set in *changes*. Returns the spawn context.
    """
    reloader._ctx = _spawn_context()
    side_effect = watch_side_effect or (lambda *paths, **kwargs: iter(changes or []))
    with patch("protean.server.reloader.watch", side_effect=side_effect):
        reloader.run()
    return reloader._ctx


class TestReloaderRun:
    def test_run_starts_the_worker_and_watches_the_reload_dirs(self, tmp_path):
        """run() installs the signal handlers, starts the worker, watches the
        reload dirs with Protean's ignore list, and stops the worker on exit."""
        reloader = Reloader(domain_path="my.domain", reload_dirs=[tmp_path])
        captured = {}

        def fake_watch(*paths, **kwargs):
            captured["paths"] = paths
            captured["kwargs"] = kwargs
            assert reloader.process is not None
            return iter([])

        ctx = _run(reloader, watch_side_effect=fake_watch)

        assert signal.getsignal(signal.SIGTERM) == reloader._handle_signal
        ctx.Process.assert_called_once()
        assert reloader.process is None
        assert captured["paths"] == (tmp_path.resolve(),)
        kwargs = captured["kwargs"]
        assert kwargs["stop_event"] is reloader.should_exit
        assert kwargs["yield_on_timeout"] is True
        assert kwargs["raise_interrupt"] is False
        assert kwargs["ignore_permission_denied"] is True
        ignore_dirs = kwargs["watch_filter"].ignore_dirs
        for extra in _EXTRA_IGNORE_DIRS:
            assert extra in ignore_dirs
        for default in PythonFilter().ignore_dirs:
            assert default in ignore_dirs

    def test_run_restarts_on_detected_changes(self, capsys):
        reloader = Reloader(domain_path="my.domain", test_mode=True)
        changes = [
            {(1, "/path/to/domain.py")},
            {(2, "/path/to/events.py")},
        ]

        ctx = _run(reloader, changes)

        # One start plus one restart per change set.
        assert ctx.Process.call_count == 3
        out = capsys.readouterr().out
        assert "Detected change in '/path/to/domain.py', restarting..." in out

    def test_run_skips_empty_change_sets(self):
        reloader = Reloader(domain_path="my.domain", test_mode=True)
        # ``yield_on_timeout=True`` causes watchfiles to yield empty sets
        # periodically. Those should not trigger a restart.
        ctx = _run(reloader, [set(), set()])

        assert ctx.Process.call_count == 1

    def test_run_stops_when_should_exit_set_mid_stream(self):
        reloader = Reloader(domain_path="my.domain", test_mode=True)

        def stream(*paths, **kwargs):
            yield {(1, "/path/to/a.py")}
            reloader.should_exit.set()
            yield {(1, "/path/to/b.py")}

        ctx = _run(reloader, watch_side_effect=stream)

        # Only the first change set caused a restart.
        assert ctx.Process.call_count == 2

    def test_run_shuts_down_on_watcher_exception(self):
        reloader = Reloader(domain_path="my.domain", test_mode=True)

        def raising_watch(*args, **kwargs):
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            _run(reloader, watch_side_effect=raising_watch)

        # The worker is still stopped on the error path.
        assert reloader.process is None

    def test_shutdown_stops_inner_process(self):
        reloader = Reloader(domain_path="my.domain")
        process = _exited_process(exitcode=3)
        reloader.process = process

        reloader._shutdown()

        process.join.assert_called()
        assert reloader.process is None
        assert reloader.exit_code == 3


class TestDisplayPath:
    def test_relative_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        nested = tmp_path / "src" / "domain.py"
        nested.parent.mkdir()
        nested.touch()

        assert _display_path(str(nested)) == "'src/domain.py'"


def _spawned_kwargs(reloader: Reloader) -> dict[str, object]:
    """Start the reloader's worker on a mocked spawn context; return its kwargs."""
    reloader._ctx = MagicMock()
    reloader._ctx.Process.return_value.pid = 1
    reloader._start_process()
    return reloader._ctx.Process.call_args.kwargs["kwargs"]


class TestReloaderLoggingArgumentValidation:
    def test_invalid_log_level_raises(self):
        with pytest.raises(ValueError, match="Invalid log_level 'VERBOSE'"):
            Reloader(domain_path="d", log_level="VERBOSE")

    def test_invalid_log_format_raises(self):
        with pytest.raises(ValueError, match="Invalid log_format 'xml'"):
            Reloader(domain_path="d", log_format="xml")

    def test_empty_log_level_does_not_hide_debug(self):
        with pytest.warns(RemovedInProtean020Warning):
            reloader = Reloader(domain_path="d", debug=True, log_level="")

        assert reloader.log_level == "DEBUG"


class TestReloaderDebugDeprecation:
    def test_debug_true_warns_and_maps_to_debug_level(self):
        with pytest.warns(RemovedInProtean020Warning, match="v0.20.0") as record:
            reloader = Reloader(domain_path="d", debug=True)

        assert len(record) == 1
        assert "Reloader(debug=...)" in str(record[0].message)
        assert 'log_level="DEBUG"' in str(record[0].message)
        assert record[0].filename == __file__
        assert _spawned_kwargs(reloader)["log_level"] == "DEBUG"

    def test_explicit_log_level_wins_over_debug(self):
        with pytest.warns(RemovedInProtean020Warning):
            reloader = Reloader(domain_path="d", debug=True, log_level="WARNING")

        assert _spawned_kwargs(reloader)["log_level"] == "WARNING"

    @pytest.mark.parametrize("kwargs", [{"debug": False}, {}], ids=["false", "omitted"])
    def test_debug_false_or_omitted_does_not_warn(self, kwargs):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            reloader = Reloader(domain_path="d", **kwargs)

        assert caught == []
        assert reloader.log_level is None
