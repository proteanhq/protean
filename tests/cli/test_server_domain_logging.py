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
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.integrations.logging import (
    ProteanCorrelationFilter,
    ProteanRedactionFilter,
)
from protean.server.supervisor import _build_queue_listener

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


def _write_domain(base: Path, logging_toml: str) -> str:
    """Write a domain module and its ``domain.toml`` into a new directory.

    Returns the module's file path, usable as ``--domain``. Each module gets
    a unique name so ``sys.modules`` never hands back an earlier test's domain.
    """
    name = f"logdomain_{uuid.uuid4().hex[:8]}"
    directory = base / name
    directory.mkdir()
    (directory / "domain.toml").write_text(textwrap.dedent(logging_toml))
    module = directory / f"{name}.py"
    module.write_text(
        f'from protean.domain import Domain\n\ndomain = Domain(name="{name}")\n'
    )
    return str(module)


def _root_filters(filter_type: type) -> list[logging.Filter]:
    return [f for f in logging.getLogger().filters if isinstance(f, filter_type)]


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


class TestMultiWorkerServer:
    def test_queue_listener_handlers_use_logging_level(self, tmp_path):
        domain = _write_domain(tmp_path, '[logging]\nlevel = "DEBUG"\n')

        with patch("protean.server.supervisor.Supervisor") as MockSupervisor:
            MockSupervisor.return_value.exit_code = 0
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

        listener = _build_queue_listener(queue.Queue())
        assert listener.handlers
        assert [h.level for h in listener.handlers] == [logging.DEBUG] * len(
            listener.handlers
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
