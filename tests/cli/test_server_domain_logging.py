"""`protean server` and `protean observatory` apply the domain's ``[logging]``.

Each test writes a domain module and a ``domain.toml`` into a temporary
directory, runs the command with the engine (or the Observatory) patched out,
and asserts the root logger's state once the command has set up logging.
"""

import json
import logging
import queue
import sys
import textwrap
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.cli._helpers import CTX_LOG_DICT_CONFIG, apply_domain_logging
from protean.integrations.logging import (
    ProteanCorrelationFilter,
    ProteanRedactionFilter,
)
from protean.server.supervisor import _build_queue_listener

pytestmark = pytest.mark.no_test_domain

runner = CliRunner()

OBSERVATORY_CLS = "protean.server.observatory.Observatory"


@pytest.fixture(autouse=True)
def _isolate_env_and_path(monkeypatch, tmp_path):
    """Run from a clean directory with no inherited log-level override."""
    monkeypatch.delenv("PROTEAN_LOG_LEVEL", raising=False)
    monkeypatch.chdir(tmp_path)
    original_path = sys.path[:]
    sys.path.insert(0, str(tmp_path))
    yield
    sys.path[:] = original_path


def _write_domain(
    base: Path, logging_toml: str, module_setup: str = "", package: bool = False
) -> str:
    """Write a domain module and its ``domain.toml`` into a new directory.

    ``module_setup`` is code placed at the top of the module, run on import.
    Returns a value usable as ``--domain``: the module's file path, or with
    ``package=True`` the name of a package whose ``__init__.py`` holds the
    domain. ``Domain.init()`` re-imports a single-file domain module while it
    traverses the directory, which would run ``module_setup`` a second time;
    a package is imported once. Each module gets
    a unique name so ``sys.modules`` never hands back an earlier test's domain.
    """
    name = f"logdomain_{uuid.uuid4().hex[:8]}"
    directory = base / name
    directory.mkdir()
    (directory / "domain.toml").write_text(textwrap.dedent(logging_toml))
    module = directory / ("__init__.py" if package else f"{name}.py")
    module.write_text(
        textwrap.dedent(module_setup)
        + f'from protean.domain import Domain\n\ndomain = Domain(name="{name}")\n'
    )
    return name if package else str(module)


def _root_filters(filter_type: type) -> list[logging.Filter]:
    return [f for f in logging.getLogger().filters if isinstance(f, filter_type)]


# A domain module that sets up its own logging when it is imported.
USER_LOGGING_SETUP = """\
import logging

_handler = logging.NullHandler()
_handler.set_name("user-handler")
logging.getLogger().addHandler(_handler)
logging.getLogger().setLevel(logging.CRITICAL)

"""


def _root_handler_names() -> list[str | None]:
    return [h.get_name() for h in logging.getLogger().handlers]


def _run_server(*args: str) -> None:
    with patch("protean.cli.Engine") as MockEngine:
        MockEngine.return_value.exit_code = 0
        result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output


def _run_observatory(*args: str) -> None:
    with patch(OBSERVATORY_CLS):
        result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output


class TestSingleWorkerServer:
    def test_applies_logging_level(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nlevel = "ERROR"\n')

        _run_server("server", "--domain", domain)

        assert logging.getLogger().level == logging.ERROR

    def test_applies_redaction_correlation_and_per_logger(self, tmp_path):
        domain = _write_domain(
            tmp_path,
            """\
            [logging]
            level = "ERROR"
            redact = ["secret"]

            [logging.per_logger]
            "some.logger" = "WARNING"
            """,
        )

        _run_server("server", "--domain", domain)

        assert len(_root_filters(ProteanRedactionFilter)) == 1
        assert len(_root_filters(ProteanCorrelationFilter)) == 1
        assert logging.getLogger("some.logger").level == logging.WARNING

    def test_env_log_level_beats_logging_table(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROTEAN_LOG_LEVEL", "WARNING")
        domain = _write_domain(tmp_path, '[logging]\nlevel = "ERROR"\n')

        _run_server("server", "--domain", domain)

        assert logging.getLogger().level == logging.WARNING

    def test_log_level_flag_overrides_level_and_keeps_redaction(self, tmp_path):
        domain = _write_domain(
            tmp_path, '[logging]\nlevel = "ERROR"\nredact = ["secret"]\n'
        )

        _run_server("--log-level", "WARNING", "server", "--domain", domain)

        assert logging.getLogger().level == logging.WARNING
        assert len(_root_filters(ProteanRedactionFilter)) == 1

    def test_log_format_flag_reaches_domain_configure_logging(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nformat = "console"\n')

        with patch("protean.domain.Domain.configure_logging") as mock_configure:
            _run_server("--log-format", "json", "server", "--domain", domain)

        mock_configure.assert_called_once_with(format="json")

    def test_log_config_replaces_logging_table(self, tmp_path):
        domain = _write_domain(
            tmp_path, '[logging]\nlevel = "ERROR"\nredact = ["secret"]\n'
        )
        config = tmp_path / "logging.json"
        config.write_text(
            json.dumps(
                {
                    "version": 1,
                    "disable_existing_loggers": False,
                    "handlers": {"console": {"class": "logging.StreamHandler"}},
                    "root": {"level": "INFO", "handlers": ["console"]},
                }
            )
        )

        _run_server("--log-config", str(config), "server", "--domain", domain)

        assert logging.getLogger().level == logging.INFO
        # Any Domain.configure_logging() call adds the redaction filter (the
        # default redact keys are non-empty), so its absence shows the call
        # was skipped.
        assert _root_filters(ProteanRedactionFilter) == []


class TestApplyDomainLoggingWithStoredDictConfig:
    """The root callback stores the parsed ``--log-config`` dict, not a flag."""

    @pytest.mark.parametrize("stored", [{"version": 1}, {}])
    def test_a_stored_dict_skips_the_logging_table(self, stored):
        domain = MagicMock()

        apply_domain_logging(domain, {CTX_LOG_DICT_CONFIG: stored})

        domain.configure_logging.assert_not_called()

    def test_no_stored_dict_applies_the_logging_table(self):
        domain = MagicMock()

        apply_domain_logging(domain, {})

        domain.configure_logging.assert_called_once_with()


class TestNoAutoLoggingOptOut:
    def test_server_keeps_logging_set_up_on_import(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROTEAN_NO_AUTO_LOGGING", "1")
        domain = _write_domain(
            tmp_path,
            '[logging]\nlevel = "ERROR"\nredact = ["secret"]\n',
            module_setup=USER_LOGGING_SETUP,
            package=True,
        )

        _run_server("server", "--domain", domain)

        assert "user-handler" in _root_handler_names()
        assert logging.getLogger().level == logging.CRITICAL
        assert _root_filters(ProteanRedactionFilter) == []

    def test_observatory_keeps_logging_set_up_on_import(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROTEAN_NO_AUTO_LOGGING", "true")
        domain = _write_domain(
            tmp_path,
            '[logging]\nlevel = "ERROR"\nredact = ["secret"]\n',
            module_setup=USER_LOGGING_SETUP,
            package=True,
        )

        _run_observatory("observatory", "--domain", domain)

        assert "user-handler" in _root_handler_names()
        assert logging.getLogger().level == logging.CRITICAL
        assert _root_filters(ProteanRedactionFilter) == []

    def test_without_opt_out_logging_table_replaces_import_setup(self, tmp_path):
        domain = _write_domain(
            tmp_path,
            '[logging]\nlevel = "ERROR"\n',
            module_setup=USER_LOGGING_SETUP,
            package=True,
        )

        _run_server("server", "--domain", domain)

        assert "user-handler" not in _root_handler_names()
        assert logging.getLogger().level == logging.ERROR


class TestMultiWorkerServer:
    def test_queue_listener_handlers_use_logging_level(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nlevel = "DEBUG"\n')
        levels_when_built: list[list[int]] = []

        def build_supervisor(*args, **kwargs):
            # Record what the listener would copy at the moment the
            # Supervisor is built, which is when the order matters.
            listener = _build_queue_listener(queue.Queue())
            levels_when_built.append([h.level for h in listener.handlers])
            supervisor = MagicMock()
            supervisor.exit_code = 0
            return supervisor

        with patch(
            "protean.server.supervisor.Supervisor", side_effect=build_supervisor
        ):
            result = runner.invoke(
                app,
                [
                    "server",
                    "--domain",
                    domain,
                    "--workers",
                    "2",
                    "--allow-event-store-multiworker",
                ],
            )
        assert result.exit_code == 0, result.output

        assert len(levels_when_built) == 1
        handler_levels = levels_when_built[0]
        assert handler_levels
        assert handler_levels == [logging.DEBUG] * len(handler_levels)


def _spawned_worker_kwargs(*args: str) -> list[dict[str, object]]:
    """Run ``protean`` with the spawn context mocked; return each worker's kwargs.

    No process starts. The Supervisor's monitor loop and the Reloader's file
    watch are patched out so the command returns once the workers are spawned.
    """
    mock_ctx = MagicMock()
    mock_process = mock_ctx.Process.return_value
    mock_process.pid = 1
    mock_process.is_alive.return_value = False
    mock_process.exitcode = 0
    with (
        patch("multiprocessing.get_context", return_value=mock_ctx),
        patch("protean.server.supervisor._build_queue_listener"),
        patch("protean.server.supervisor.Supervisor._install_signal_handlers"),
        patch("protean.server.supervisor.Supervisor._monitor"),
        patch("protean.server.reloader.Reloader._install_signal_handlers"),
        patch("protean.server.reloader.watch", return_value=iter([])),
    ):
        result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    calls = mock_ctx.Process.call_args_list
    assert calls
    return [call.kwargs["kwargs"] for call in calls]


MULTI_WORKER = ("--workers", "2", "--allow-event-store-multiworker")


class TestFlagsReachWorkerProcesses:
    def test_log_level_reaches_every_multi_worker_process(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nlevel = "INFO"\n')

        spawned = _spawned_worker_kwargs(
            "--log-level", "DEBUG", "server", "--domain", domain, *MULTI_WORKER
        )

        assert len(spawned) == 2
        assert [kwargs["log_level"] for kwargs in spawned] == ["DEBUG", "DEBUG"]
        assert [kwargs["log_format"] for kwargs in spawned] == [None, None]
        assert [kwargs["log_config"] for kwargs in spawned] == [None, None]

    def test_log_format_reaches_every_multi_worker_process(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nformat = "console"\n')

        spawned = _spawned_worker_kwargs(
            "--log-format", "json", "server", "--domain", domain, *MULTI_WORKER
        )

        assert len(spawned) == 2
        assert [kwargs["log_format"] for kwargs in spawned] == ["json", "json"]
        assert [kwargs["log_level"] for kwargs in spawned] == [None, None]

    def test_log_config_dict_reaches_every_multi_worker_process(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nlevel = "ERROR"\n')
        payload = {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {"console": {"class": "logging.StreamHandler"}},
            "root": {"level": "WARNING", "handlers": ["console"]},
        }
        config = tmp_path / "logging.json"
        config.write_text(json.dumps(payload))

        spawned = _spawned_worker_kwargs(
            "--log-config", str(config), "server", "--domain", domain, *MULTI_WORKER
        )

        assert len(spawned) == 2
        assert [kwargs["log_config"] for kwargs in spawned] == [payload, payload]

    def test_log_level_reaches_the_reload_worker(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nlevel = "INFO"\n')

        spawned = _spawned_worker_kwargs(
            "--log-level", "DEBUG", "server", "--domain", domain, "--reload"
        )

        assert spawned == [
            {"log_level": "DEBUG", "log_format": None, "log_config": None}
        ]

    def test_log_format_reaches_the_reload_worker(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nlevel = "INFO"\n')

        spawned = _spawned_worker_kwargs(
            "--log-format", "json", "server", "--domain", domain, "--reload"
        )

        assert spawned == [
            {"log_level": None, "log_format": "json", "log_config": None}
        ]

    def test_no_flags_send_no_overrides(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nlevel = "INFO"\n')

        spawned = _spawned_worker_kwargs("server", "--domain", domain, *MULTI_WORKER)

        assert (
            spawned == [{"log_level": None, "log_format": None, "log_config": None}] * 2
        )


class TestObservatory:
    def test_applies_logging_level(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nlevel = "ERROR"\n')

        _run_observatory("observatory", "--domain", domain)

        assert logging.getLogger().level == logging.ERROR

    @pytest.mark.parametrize(
        ("first", "second", "expected"),
        [
            ("ERROR", "WARNING", logging.ERROR),
            ("WARNING", "ERROR", logging.WARNING),
        ],
    )
    def test_first_domain_logging_wins(self, tmp_path, first, second, expected):
        first_domain = _write_domain(tmp_path, f'[logging]\nlevel = "{first}"\n')
        second_domain = _write_domain(tmp_path, f'[logging]\nlevel = "{second}"\n')

        _run_observatory(
            "observatory", "--domain", first_domain, "--domain", second_domain
        )

        assert logging.getLogger().level == expected

    def test_log_level_flag_overrides_level_and_keeps_redaction(self, tmp_path):
        domain = _write_domain(
            tmp_path, '[logging]\nlevel = "ERROR"\nredact = ["secret"]\n'
        )

        _run_observatory("--log-level", "WARNING", "observatory", "--domain", domain)

        assert logging.getLogger().level == logging.WARNING
        assert len(_root_filters(ProteanRedactionFilter)) == 1
