"""Tests for the development Reloader.

The Reloader spawns child processes and watches files, so these tests
exercise initialization, process lifecycle, signal handling, and the
watchfiles integration without spawning real worker processes or
triggering real filesystem events.
"""

import os
import signal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from protean.server.reloader import (
    _DRAIN_MARGIN_SECONDS,
    _EXTRA_IGNORE_DIRS,
    _SHUTDOWN_TIMEOUT_SECONDS,
    Reloader,
    _display_path,
)
from protean.server.supervisor import _worker_entry


class TestReloaderInit:
    def test_initialization_with_defaults(self):
        reloader = Reloader(domain_path="my.domain")

        assert reloader.domain_path == "my.domain"
        assert reloader.test_mode is False
        assert reloader.debug is False
        assert reloader.reload_dirs == [Path.cwd().resolve()]
        assert reloader.exit_code == 0
        assert reloader.process is None
        assert reloader._shutting_down is False
        assert reloader.should_exit.is_set() is False

    def test_initialization_with_explicit_args(self, tmp_path):
        sub = tmp_path / "src"
        sub.mkdir()

        reloader = Reloader(
            domain_path="svc.domain",
            reload_dirs=[str(sub)],
            test_mode=True,
            debug=True,
        )

        assert reloader.domain_path == "svc.domain"
        assert reloader.test_mode is True
        assert reloader.debug is True
        assert reloader.reload_dirs == [sub.resolve()]

    def test_reload_dirs_accepts_path_objects(self, tmp_path):
        reloader = Reloader(
            domain_path="svc.domain",
            reload_dirs=[tmp_path, tmp_path / "nested"],
        )

        assert reloader.reload_dirs == [
            tmp_path.resolve(),
            (tmp_path / "nested").resolve(),
        ]

    def test_empty_reload_dirs_falls_back_to_cwd(self):
        reloader = Reloader(domain_path="svc.domain", reload_dirs=[])

        assert reloader.reload_dirs == [Path.cwd().resolve()]


class TestReloaderProcessLifecycle:
    def test_start_process_spawns_worker_with_correct_args(self):
        reloader = Reloader(domain_path="my.domain", test_mode=True, debug=False)

        mock_process = MagicMock()
        mock_process.pid = 4242
        reloader._ctx = MagicMock()
        reloader._ctx.Process.return_value = mock_process

        reloader._start_process()

        reloader._ctx.Process.assert_called_once_with(
            target=_worker_entry,
            args=("my.domain", True, False, 0, None),
            name="protean-reload-worker",
        )
        mock_process.start.assert_called_once()
        assert reloader.process is mock_process

    def test_stop_process_sends_sigterm_and_joins(self):
        reloader = Reloader(domain_path="my.domain")

        # ``is_alive`` reports True before the join (to trigger SIGTERM) and
        # False after, so the kill fallback does not fire.
        alive_states = iter([True, False, False])
        mock_process = MagicMock()
        mock_process.is_alive.side_effect = lambda: next(alive_states)
        mock_process.pid = 1234
        mock_process.exitcode = 0
        reloader.process = mock_process

        with patch("os.kill") as mock_kill:
            reloader._stop_process()

        mock_kill.assert_called_once_with(1234, signal.SIGTERM)
        mock_process.join.assert_called_once()
        mock_process.kill.assert_not_called()
        assert reloader.process is None

    def test_stop_process_is_noop_when_no_process(self):
        reloader = Reloader(domain_path="my.domain")
        # No process attached — should not raise.
        reloader._stop_process()
        assert reloader.process is None

    def test_stop_process_tolerates_process_lookup_error(self):
        reloader = Reloader(domain_path="my.domain")

        alive_states = iter([True, False, False])
        mock_process = MagicMock()
        mock_process.is_alive.side_effect = lambda: next(alive_states)
        mock_process.pid = 1234
        mock_process.exitcode = 0
        reloader.process = mock_process

        with patch("os.kill", side_effect=ProcessLookupError):
            # Should not raise
            reloader._stop_process()

        mock_process.join.assert_called_once()
        mock_process.kill.assert_not_called()
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

    def test_stop_process_captures_nonzero_exit_code(self):
        reloader = Reloader(domain_path="my.domain")

        mock_process = MagicMock()
        mock_process.is_alive.return_value = False
        mock_process.pid = 1234
        mock_process.exitcode = 42
        reloader.process = mock_process

        reloader._stop_process()

        assert reloader.exit_code == 42
        assert reloader.process is None

    def test_restart_process_stops_then_starts(self):
        reloader = Reloader(domain_path="my.domain")
        reloader._stop_process = MagicMock()
        reloader._start_process = MagicMock()

        reloader._restart_process()

        reloader._stop_process.assert_called_once()
        reloader._start_process.assert_called_once()

    def test_restart_process_does_not_start_when_exiting(self):
        reloader = Reloader(domain_path="my.domain")
        reloader._stop_process = MagicMock()
        reloader._start_process = MagicMock()
        reloader.should_exit.set()

        reloader._restart_process()

        reloader._stop_process.assert_called_once()
        reloader._start_process.assert_not_called()

    def test_restart_process_clears_prior_exit_code(self):
        reloader = Reloader(domain_path="my.domain")
        reloader._stop_process = MagicMock()
        reloader._start_process = MagicMock()
        reloader.exit_code = 7

        reloader._restart_process()

        assert reloader.exit_code == 0


class TestReloaderTerminationBudget:
    """The join budget follows the Engine's configured drain window.

    The worker waits ``[server].drain_timeout`` for in-flight handlers before
    force-cancelling them, so a flat 10-second join would kill it mid-drain
    whenever that window is longer.
    """

    def _reloader_with_window(self, window):
        """A Reloader whose on-disk config reports *window* as drain_timeout."""
        reloader = Reloader(domain_path="my.domain")
        config = {"server": {"drain_timeout": window}}
        return reloader, patch(
            "protean.domain.config.Config2.load_from_path", return_value=config
        )

    def test_budget_covers_a_longer_drain_window(self):
        reloader, patched = self._reloader_with_window(20)
        with patched:
            assert reloader._termination_timeout() == 20 + _DRAIN_MARGIN_SECONDS

    def test_budget_never_shrinks_below_the_default(self):
        """A short window does not shorten the budget below 10 seconds."""
        reloader, patched = self._reloader_with_window(2)
        with patched:
            assert reloader._termination_timeout() == float(_SHUTDOWN_TIMEOUT_SECONDS)

    @pytest.mark.parametrize(
        "window", ["not-a-number", True, 0, -5, float("nan"), float("inf")]
    )
    def test_invalid_window_falls_back_to_the_default(self, window):
        """Values the Engine rejects do not stretch or shrink the budget."""
        reloader, patched = self._reloader_with_window(window)
        with patched:
            assert reloader._termination_timeout() == float(_SHUTDOWN_TIMEOUT_SECONDS)

    def test_unreadable_config_falls_back_to_the_default(self):
        """The config may not read here; the worker surfaces the real error."""
        reloader = Reloader(domain_path="my.domain")
        with patch(
            "protean.domain.config.Config2.load_from_path",
            side_effect=ValueError("bad TOML"),
        ):
            assert reloader._termination_timeout() == float(_SHUTDOWN_TIMEOUT_SECONDS)

    def test_missing_drain_timeout_falls_back_to_the_default(self):
        """A config with no server.drain_timeout uses the default budget."""
        reloader = Reloader(domain_path="my.domain")
        with patch(
            "protean.domain.config.Config2.load_from_path", return_value={"server": {}}
        ):
            assert reloader._termination_timeout() == float(_SHUTDOWN_TIMEOUT_SECONDS)

    def test_budget_is_read_fresh_each_call(self):
        """A domain.toml edit mid-run must be picked up, so the window is read
        on every call, not cached."""
        reloader, patched = self._reloader_with_window(20)
        with patched as mock_load:
            reloader._termination_timeout()
            reloader._termination_timeout()
        assert mock_load.call_count == 2

    def test_start_process_binds_the_budget_from_current_config(self):
        """_start_process sizes the join budget from the config as it stands,
        so the worker it spawns is later joined with its own window."""
        reloader, patched = self._reloader_with_window(20)
        reloader._ctx = MagicMock()
        with patched:
            reloader._start_process()
        assert reloader._stop_timeout == 20 + _DRAIN_MARGIN_SECONDS

    def test_budget_refreshes_between_worker_generations(self):
        """A domain.toml change between restarts binds the new window to the
        replacement worker, not the value read when the reloader started."""
        reloader = Reloader(domain_path="my.domain")
        reloader._ctx = MagicMock()
        configs = iter(
            [{"server": {"drain_timeout": 20}}, {"server": {"drain_timeout": 40}}]
        )
        with patch(
            "protean.domain.config.Config2.load_from_path",
            side_effect=lambda _path: next(configs),
        ):
            reloader._start_process()
            assert reloader._stop_timeout == 20 + _DRAIN_MARGIN_SECONDS
            reloader._start_process()
            assert reloader._stop_timeout == 40 + _DRAIN_MARGIN_SECONDS

    def test_stop_process_joins_for_the_bound_budget(self):
        """The join uses the budget bound when the worker started, so a 20s
        drain is not cut at 10 and a later config edit cannot shorten it."""
        reloader = Reloader(domain_path="my.domain")
        reloader._stop_timeout = 20 + _DRAIN_MARGIN_SECONDS

        mock_process = MagicMock()
        alive_states = iter([True, False, False])
        mock_process.is_alive.side_effect = lambda: next(alive_states)
        mock_process.pid = 1234
        mock_process.exitcode = 0
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

    def test_dotted_module_falls_back_to_cwd(self):
        """A dotted module cannot be resolved to a file without importing it, so
        the working directory (where ``domain.toml`` conventionally lives) is
        used."""
        reloader = Reloader(domain_path="my.package.domain")
        assert reloader._config_search_root() == os.getcwd()


class TestReloaderSignalHandling:
    def test_install_signal_handlers(self):
        reloader = Reloader(domain_path="my.domain")
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        try:
            reloader._install_signal_handlers()
            assert signal.getsignal(signal.SIGINT) == reloader._handle_signal
            assert signal.getsignal(signal.SIGTERM) == reloader._handle_signal
        finally:
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

    def test_sighup_handler_installed(self):
        reloader = Reloader(domain_path="my.domain")
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sighup = signal.getsignal(signal.SIGHUP)

        try:
            reloader._install_signal_handlers()
            assert signal.getsignal(signal.SIGHUP) == reloader._handle_signal
        finally:
            signal.signal(signal.SIGHUP, original_sighup)
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)

    def test_handle_signal_sets_should_exit(self):
        reloader = Reloader(domain_path="my.domain")

        reloader._handle_signal(signal.SIGTERM, None)

        assert reloader._shutting_down is True
        assert reloader.should_exit.is_set() is True

    def test_handle_signal_is_idempotent(self):
        reloader = Reloader(domain_path="my.domain")

        reloader._handle_signal(signal.SIGTERM, None)
        reloader._handle_signal(signal.SIGINT, None)

        # Still exactly one shutdown request.
        assert reloader._shutting_down is True
        assert reloader.should_exit.is_set() is True


class TestReloaderRun:
    def _make_reloader(self):
        reloader = Reloader(domain_path="my.domain", test_mode=True)
        reloader._start_process = MagicMock()
        reloader._restart_process = MagicMock()
        reloader._shutdown = MagicMock()
        reloader._install_signal_handlers = MagicMock()
        return reloader

    def test_run_starts_process_and_installs_signals(self):
        reloader = self._make_reloader()

        with patch("protean.server.reloader.watch", return_value=iter([])):
            reloader.run()

        reloader._install_signal_handlers.assert_called_once()
        reloader._start_process.assert_called_once()
        reloader._shutdown.assert_called_once()

    def test_run_restarts_on_detected_changes(self):
        reloader = self._make_reloader()
        changes = [
            {(1, "/path/to/domain.py")},
            {(2, "/path/to/events.py")},
        ]

        with patch("protean.server.reloader.watch", return_value=iter(changes)):
            reloader.run()

        assert reloader._restart_process.call_count == 2

    def test_run_skips_empty_change_sets(self):
        reloader = self._make_reloader()
        # ``yield_on_timeout=True`` causes watchfiles to yield empty sets
        # periodically. Those should not trigger a restart.
        changes = [set(), set()]

        with patch("protean.server.reloader.watch", return_value=iter(changes)):
            reloader.run()

        reloader._restart_process.assert_not_called()

    def test_run_stops_when_should_exit_set_mid_stream(self):
        reloader = self._make_reloader()

        def stream():
            yield {(1, "/path/to/a.py")}
            reloader.should_exit.set()
            yield {(1, "/path/to/b.py")}

        with patch("protean.server.reloader.watch", return_value=stream()):
            reloader.run()

        # Only the first iteration should have caused a restart.
        assert reloader._restart_process.call_count == 1

    def test_run_passes_reload_dirs_to_watchfiles(self, tmp_path):
        reloader = Reloader(domain_path="my.domain", reload_dirs=[tmp_path])
        reloader._start_process = MagicMock()
        reloader._shutdown = MagicMock()
        reloader._install_signal_handlers = MagicMock()

        captured = {}

        def fake_watch(*paths, **kwargs):
            captured["paths"] = paths
            captured["kwargs"] = kwargs
            return iter([])

        with patch("protean.server.reloader.watch", side_effect=fake_watch):
            reloader.run()

        assert captured["paths"] == (tmp_path.resolve(),)
        assert captured["kwargs"]["stop_event"] is reloader.should_exit
        assert captured["kwargs"]["yield_on_timeout"] is True
        assert captured["kwargs"]["raise_interrupt"] is False

    def test_run_filter_extends_default_ignore_dirs(self, tmp_path):
        reloader = Reloader(domain_path="my.domain", reload_dirs=[tmp_path])
        reloader._start_process = MagicMock()
        reloader._shutdown = MagicMock()
        reloader._install_signal_handlers = MagicMock()

        captured = {}

        def fake_watch(*paths, **kwargs):
            captured["filter"] = kwargs["watch_filter"]
            return iter([])

        with patch("protean.server.reloader.watch", side_effect=fake_watch):
            reloader.run()

        watch_filter = captured["filter"]
        for extra in _EXTRA_IGNORE_DIRS:
            assert extra in watch_filter.ignore_dirs

    def test_run_shuts_down_on_watcher_exception(self):
        reloader = self._make_reloader()

        def raising_watch(*args, **kwargs):
            raise RuntimeError("boom")

        with patch("protean.server.reloader.watch", side_effect=raising_watch):
            with pytest.raises(RuntimeError, match="boom"):
                reloader.run()

        # ``_shutdown`` must still run on the error path so the inner
        # process is cleaned up.
        reloader._shutdown.assert_called_once()

    def test_shutdown_stops_inner_process(self):
        reloader = Reloader(domain_path="my.domain")
        reloader._stop_process = MagicMock()

        reloader._shutdown()

        reloader._stop_process.assert_called_once()


class TestDisplayPath:
    def test_relative_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        nested = tmp_path / "src" / "domain.py"
        nested.parent.mkdir()
        nested.touch()

        assert _display_path(str(nested)) == "'src/domain.py'"

    def test_absolute_when_outside_cwd(self, tmp_path):
        outside = Path("/etc/hosts")
        rendered = _display_path(str(outside))
        # Either relative (if cwd happens to contain /etc/hosts, which it
        # doesn't in practice) or an absolute string wrapped in quotes.
        assert rendered.startswith("'") and rendered.endswith("'")
