"""CLI smoke tests for ``protean upgrade-check``."""

import json

import pytest
from typer.testing import CliRunner

from protean import upgrade_opportunities
from protean.cli import app
from protean.cli.upgrade import _print_rich
from protean.domain import Domain
from protean.upgrade import UpgradeFinding

runner = CliRunner()

# A clean, in-memory support domain (no external infra needed to init).
_DOMAIN = "tests/support/domains/test19/domain19.py:domain"

# A domain that hand-rolls raw SQL through `sqlalchemy.text(...)`, for the
# --opportunities mode.
_TEXT_DOMAIN = "tests/support/domains/opportunities/domain_text.py:domain"


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


class TestOpportunitiesCLI:
    def test_opportunities_rich_run_reports_the_raw_sql_detector(self):
        result = runner.invoke(
            app, ["upgrade-check", "-d", _TEXT_DOMAIN, "--opportunities"]
        )
        # Opportunities are advisory (info), so an info-only run exits 0.
        assert result.exit_code == 0
        assert "OPPORTUNITY_QUERY_API" in result.stdout

    def test_opportunities_json_is_upgradefinding_shaped(self):
        result = runner.invoke(
            app,
            [
                "upgrade-check",
                "-d",
                _TEXT_DOMAIN,
                "--opportunities",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert isinstance(payload, list)
        query_api = [f for f in payload if f["code"] == "OPPORTUNITY_QUERY_API"]
        assert len(query_api) == 1
        assert set(query_api[0]) == {
            "code",
            "level",
            "title",
            "detail",
            "remediation",
            "element",
            "sql",
        }

    def test_pinned_version_below_the_release_suppresses_the_finding(self):
        # The query API arrived in 0.16.0; pinning to 0.15.0 says the domain does
        # not own it yet, so the finding must not appear.
        result = runner.invoke(
            app,
            [
                "upgrade-check",
                "-d",
                _TEXT_DOMAIN,
                "--opportunities",
                "--pinned-version",
                "0.15.0",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert not any(f["code"] == "OPPORTUNITY_QUERY_API" for f in payload)

    @pytest.mark.parametrize(
        "pinned", ["latest", "0.16latest", "0.16.3oops", "0.16.", "0.16.3rc", "x.y.z"]
    )
    def test_bad_pinned_version_exits_1(self, pinned):
        result = runner.invoke(
            app,
            [
                "upgrade-check",
                "-d",
                _TEXT_DOMAIN,
                "--opportunities",
                "--pinned-version",
                pinned,
            ],
        )
        assert result.exit_code == 1
        assert "Invalid --pinned-version" in result.stdout

    def test_pinned_version_without_opportunities_exits_1(self):
        # --pinned-version only affects --opportunities mode; passing it without
        # that flag is a mistake, not a silently ignored option.
        result = runner.invoke(
            app,
            [
                "upgrade-check",
                "-d",
                _TEXT_DOMAIN,
                "--pinned-version",
                "0.16",
            ],
        )
        assert result.exit_code == 1
        assert "--pinned-version applies only with --opportunities" in result.stdout

    @pytest.mark.parametrize(
        "pinned", ["0.16", "0.16.3", "0.16.0rc1", "0.16.0a1", "0.16.0b2", "0.16.0.dev1"]
    )
    def test_pinned_version_accepts_semver_and_release_tags(self, pinned):
        result = runner.invoke(
            app,
            [
                "upgrade-check",
                "-d",
                _TEXT_DOMAIN,
                "--opportunities",
                "--pinned-version",
                pinned,
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        assert "Invalid --pinned-version" not in result.stdout

    def test_opportunities_does_not_initialize_adapters(self, monkeypatch):
        # Opportunity checks read source off disk, so they must not need working
        # infrastructure. Standing in for unreachable adapters: an init that
        # blows up must not reach the report.
        def boom(self, *args, **kwargs):
            raise RuntimeError("adapters unreachable")

        monkeypatch.setattr(Domain, "init", boom)
        result = runner.invoke(
            app, ["upgrade-check", "-d", _TEXT_DOMAIN, "--opportunities"]
        )
        assert result.exit_code == 0
        assert "OPPORTUNITY_QUERY_API" in result.stdout

    def test_a_failing_detector_surfaces_check_failed_and_exits_2(self, monkeypatch):
        # Detector findings are advisory, but a detector that cannot complete is
        # a CHECK_FAILED warning, and any warning exits 2 through the CLI.
        def boom(trees, pinned):
            raise RuntimeError("detector blew up")

        monkeypatch.setattr(upgrade_opportunities, "_DETECTORS", (boom,))
        result = runner.invoke(
            app, ["upgrade-check", "-d", _TEXT_DOMAIN, "--opportunities"]
        )
        assert result.exit_code == 2
        assert "CHECK_FAILED" in result.stdout


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
