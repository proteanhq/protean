"""Top-level ``[lint]`` and ``[observatory]`` tables reach the loaded config.

Each test goes through the config loader (a TOML file, ``pyproject.toml`` or a
``config=`` dict). Setting ``domain.config["lint"]`` after construction would skip
the loader, which is the path these tables used to be dropped on.
"""

import json
import textwrap

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.domain import Domain
from protean.domain.config import Config2

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_protean_env(monkeypatch):
    monkeypatch.delenv("PROTEAN_ENV", raising=False)


def _write(path, text):
    path.write_text(textwrap.dedent(text))


@pytest.mark.no_test_domain
class TestLintTableLoads:
    def test_from_domain_toml(self, tmp_path):
        _write(tmp_path / "domain.toml", '[lint]\nlevel = "error"\n')

        config = Config2.load_from_path(str(tmp_path))

        assert config["lint"]["level"] == "error"

    def test_from_pyproject_toml(self, tmp_path):
        _write(tmp_path / "pyproject.toml", '[tool.protean.lint]\nlevel = "error"\n')

        config = Config2.load_from_path(str(tmp_path))

        assert config["lint"]["level"] == "error"

    def test_nested_suppressions_and_rules_load(self, tmp_path):
        _write(
            tmp_path / "domain.toml",
            """
            [lint]
            rules = ["my_app.lint.check_names"]

            [lint.suppressions]
            UNHANDLED_EVENT = 3
            """,
        )

        config = Config2.load_from_path(str(tmp_path))

        assert config["lint"] == {
            "rules": ["my_app.lint.check_names"],
            "suppressions": {"UNHANDLED_EVENT": 3},
        }

    def test_from_config_dict(self):
        domain = Domain(name="LintDict", config={"lint": {"level": "error"}})

        assert domain.config["lint"]["level"] == "error"

    def test_env_overlay_overrides_base_table(self, tmp_path, monkeypatch):
        _write(
            tmp_path / "domain.toml",
            """
            [lint]
            level = "warn"

            [test.lint]
            level = "error"
            """,
        )
        monkeypatch.setenv("PROTEAN_ENV", "test")

        config = Config2.load_from_path(str(tmp_path))

        assert config["lint"]["level"] == "error"

    def test_base_table_applies_without_env(self, tmp_path):
        _write(
            tmp_path / "domain.toml",
            """
            [lint]
            level = "warn"

            [test.lint]
            level = "error"
            """,
        )

        config = Config2.load_from_path(str(tmp_path))

        assert config["lint"]["level"] == "warn"


@pytest.mark.no_test_domain
class TestObservatoryTableLoads:
    def test_from_domain_toml(self, tmp_path):
        _write(tmp_path / "domain.toml", "[observatory]\ntrace_retention_days = 3\n")

        config = Config2.load_from_path(str(tmp_path))

        assert config["observatory"]["trace_retention_days"] == 3

    def test_from_pyproject_toml(self, tmp_path):
        _write(
            tmp_path / "pyproject.toml",
            "[tool.protean.observatory]\ntrace_retention_days = 3\n",
        )

        config = Config2.load_from_path(str(tmp_path))

        assert config["observatory"]["trace_retention_days"] == 3

    def test_from_config_dict(self):
        domain = Domain(
            name="ObservatoryDict", config={"observatory": {"trace_retention_days": 3}}
        )

        assert domain.config["observatory"]["trace_retention_days"] == 3

    def test_trace_emitter_uses_loaded_retention(self, tmp_path):
        _write(tmp_path / "domain.toml", "[observatory]\ntrace_retention_days = 3\n")

        domain = Domain(root_path=str(tmp_path), name="ObservatoryToml")

        assert domain.trace_emitter._retention_ms == 3 * 86_400_000

    def test_trace_emitter_falls_back_when_observatory_is_not_a_table(self, tmp_path):
        _write(tmp_path / "domain.toml", 'observatory = "on"\n')

        domain = Domain(root_path=str(tmp_path), name="ObservatoryScalar")

        assert domain.trace_emitter._retention_ms == 7 * 86_400_000


@pytest.mark.no_test_domain
class TestTablesDefaultToEmpty:
    def test_absent_from_domain_toml(self, tmp_path):
        _write(tmp_path / "domain.toml", 'identity_strategy = "uuid"\n')

        config = Config2.load_from_path(str(tmp_path))

        assert config["lint"] == {}
        assert config["observatory"] == {}

    @pytest.mark.parametrize("source", [None, {}])
    def test_absent_from_config_dict(self, source):
        config = Config2.load_from_dict(source)

        assert config["lint"] == {}
        assert config["observatory"] == {}

    def test_default_trace_retention_without_table(self, tmp_path):
        _write(tmp_path / "domain.toml", 'identity_strategy = "uuid"\n')

        domain = Domain(root_path=str(tmp_path), name="NoObservatory")

        assert domain.trace_emitter._retention_ms == 7 * 86_400_000


# An aggregate whose only finding is an info-level EVENT_WITHOUT_DATA. Under the
# default ``[lint].level = "warn"`` that finding does not fail the run; under
# ``level = "info"`` it does.
_INFO_ONLY_DOMAIN = """
from protean import Domain
from protean.fields import String
from protean.utils.mixins import handle

domain = Domain(name="{name}")


@domain.aggregate
class Order:
    name = String(max_length=100)


@domain.command(part_of=Order)
class PlaceOrder:
    name = String(required=True)


@domain.event(part_of=Order)
class OrderNudged:
    pass


@domain.command_handler(part_of=Order)
class OrderHandler:
    @handle(PlaceOrder)
    def place(self, command):
        pass


@domain.event_handler(part_of=Order)
class OrderEventHandler:
    @handle(OrderNudged)
    def on_nudged(self, event):
        pass
"""


@pytest.mark.no_test_domain
class TestCheckReadsLintTableFromDomainToml:
    def _run_check(self, tmp_path, monkeypatch, module_name, toml):
        _write(tmp_path / "domain.toml", toml)
        (tmp_path / f"{module_name}.py").write_text(
            _INFO_ONLY_DOMAIN.format(name=module_name)
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))
        return runner.invoke(
            app, ["check", "-d", f"{module_name}.py:domain", "--format", "json"]
        )

    def test_lint_level_info_gates_info_finding(self, tmp_path, monkeypatch):
        result = self._run_check(
            tmp_path, monkeypatch, "lint_info_gates", '[lint]\nlevel = "info"\n'
        )

        # A crash also exits 1, so check that the exit came from the gate.
        assert isinstance(result.exception, SystemExit), result.output
        assert result.exit_code == 1, result.output
        # Debug log lines from domain discovery come before the JSON document.
        lines = result.output.splitlines()
        payload = json.loads("\n".join(lines[lines.index("{") :]))
        assert payload["status"] == "fail"
        assert payload["data"]["counts"]["warnings"] == 0
        assert {d["level"] for d in payload["diagnostics"]} == {"info"}
        assert "EVENT_WITHOUT_DATA" in {d["code"] for d in payload["diagnostics"]}

    def test_without_lint_table_info_finding_passes(self, tmp_path, monkeypatch):
        result = self._run_check(
            tmp_path, monkeypatch, "lint_info_default", 'identity_strategy = "uuid"\n'
        )

        assert result.exit_code == 0, result.output

    def test_bad_lint_option_is_a_usage_error(self, tmp_path, monkeypatch):
        result = self._run_check(
            tmp_path, monkeypatch, "lint_bad_rules", "[lint]\nrules = 5\n"
        )

        assert result.exit_code == 2, result.output
        assert "[lint].rules must be a list" in result.output

    def test_bad_lint_option_fails_verify_check_stage(self, tmp_path, monkeypatch):
        _write(tmp_path / "domain.toml", '[lint]\naggregate_size_limit = "5"\n')
        (tmp_path / "lint_bad_limit.py").write_text(
            _INFO_ONLY_DOMAIN.format(name="lint_bad_limit")
        )
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.syspath_prepend(str(tmp_path))

        result = runner.invoke(
            app,
            [
                "verify",
                "-d",
                "lint_bad_limit.py:domain",
                "--path",
                str(empty),
                "--json",
            ],
        )

        assert result.exit_code == 4, result.output
        lines = result.stdout.splitlines()
        data = json.loads("\n".join(lines[lines.index("{") :]))
        messages = " ".join(
            e["message"] for e in data["data"]["stages"]["check"]["errors"]
        )
        assert "[lint].aggregate_size_limit must be a non-negative integer" in messages
