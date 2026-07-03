"""CLI smoke tests for ``protean upgrade-check``."""

import json

from typer.testing import CliRunner

from protean.cli import app
from protean.cli.upgrade import _print_rich
from protean.upgrade import UpgradeFinding

runner = CliRunner()

# A clean, in-memory support domain (no external infra needed to init).
_DOMAIN = "tests/support/domains/test19/domain19.py:domain"


class TestUpgradeCheckCLI:
    def test_runs_and_reports_info(self):
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        # The health-port note always fires (info), so an in-memory domain is a
        # clean, info-only run -> exit 0.
        assert result.exit_code == 0
        assert "health-check" in result.stdout

    def test_json_output_is_a_list_of_findings(self):
        result = runner.invoke(
            app, ["upgrade-check", "-d", _DOMAIN, "--format", "json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert isinstance(payload, list)
        assert any(f["code"] == "HEALTH_PORT_BIND" for f in payload)

    def test_bad_domain_path_exits_1(self):
        result = runner.invoke(app, ["upgrade-check", "-d", "nonexistent.module"])
        assert result.exit_code == 1

    def test_invalid_format_fails_fast(self):
        result = runner.invoke(
            app, ["upgrade-check", "-d", _DOMAIN, "--format", "yaml"]
        )
        assert result.exit_code == 1
        assert "Invalid --format" in result.stdout


class TestPrintRich:
    def test_no_findings_reports_ready(self, capsys):
        _print_rich("App", [])
        out = capsys.readouterr().out
        assert "READY" in out
        assert "No upgrade actions" in out

    def test_renders_warnings_infos_and_sql(self, capsys):
        findings = [
            UpgradeFinding(
                code="HEALTH_PORT_BIND",
                level="info",
                title="health note",
                detail="d",
                remediation="r",
            ),
            UpgradeFinding(
                code="OUTBOX_NEEDS_ALTER",
                level="warning",
                title="outbox note",
                detail="d2",
                remediation="r2",
                element="databases.default",
                sql="ALTER TABLE outbox\n  ALTER COLUMN status TYPE varchar(32);",
            ),
        ]
        _print_rich("App", findings)
        out = capsys.readouterr().out
        assert "REVIEW" in out
        assert "warning(s)" in out and "info(s)" in out
        assert "Generated SQL" in out
        assert "ALTER COLUMN status" in out
        assert "(databases.default)" in out
