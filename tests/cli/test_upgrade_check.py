"""CLI smoke tests for ``protean upgrade-check``."""

import json

from typer.testing import CliRunner

from protean.cli import app

runner = CliRunner()

# A clean, in-memory support domain (no external infra needed to init).
_DOMAIN = "tests/support/domains/test19/domain19.py:domain"


class TestUpgradeCheckCLI:
    def test_runs_and_reports_info(self):
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        # The health-port note always fires (info), so an in-memory domain is a
        # clean, info-only run -> exit 0.
        assert result.exit_code == 0
        assert "health-check port" in result.stdout

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
