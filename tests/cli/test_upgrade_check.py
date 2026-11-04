"""CLI smoke tests for ``protean upgrade-check``."""

import json
import sys

import pytest
import typer
from typer.testing import CliRunner

from protean import upgrade_opportunities
from protean.cli import app
from protean.cli import upgrade as upgrade_cli
from protean.cli.upgrade import _print_rich
from protean.domain import Domain
from protean.upgrade import UpgradeFinding

runner = CliRunner()

# A clean, in-memory support domain (no external infra needed to init).
_DOMAIN = "tests/support/domains/test19/domain19.py:domain"

# A domain that hand-rolls raw SQL through `sqlalchemy.text(...)`, for the
# --opportunities mode.
_TEXT_DOMAIN = "tests/support/domains/opportunities/domain_text.py:domain"

_WARNING = UpgradeFinding(
    code="POOL_DEFAULTS_CHANGED",
    level="warning",
    title="pool note",
    detail="d",
    remediation="r",
)


def _stderr(result):
    # Rich wraps stderr to the terminal width; join the lines before matching.
    return " ".join(result.stderr.split())


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

    def test_bad_domain_path_exits_2_on_stderr(self):
        result = runner.invoke(app, ["upgrade-check", "-d", "nonexistent.module"])
        assert result.exit_code == 2
        assert "Error loading Protean domain" in _stderr(result)
        assert result.stdout == ""

    def test_invalid_format_exits_2_on_stderr(self):
        result = runner.invoke(
            app, ["upgrade-check", "-d", _DOMAIN, "--format", "yaml"]
        )
        assert result.exit_code == 2
        assert "Invalid --format: 'yaml'" in _stderr(result)
        assert result.stdout == ""


class TestUpgradeCheckExitCodes:
    """Warnings exit 1, a clean or info-only run exits 0, and every usage or
    environment error exits 2 with its message on stderr and stdout empty."""

    @pytest.fixture(autouse=True)
    def _restore_sys_path(self):
        original_path = sys.path[:]
        yield
        sys.path[:] = original_path

    def test_warning_run_exits_1(self, monkeypatch):
        monkeypatch.setattr(upgrade_cli, "run_upgrade_checks", lambda d: [_WARNING])
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        assert result.exit_code == 1
        assert "POOL_DEFAULTS_CHANGED" in result.stdout

    def test_warning_run_exits_1_under_json(self, monkeypatch):
        monkeypatch.setattr(upgrade_cli, "run_upgrade_checks", lambda d: [_WARNING])
        result = runner.invoke(
            app, ["upgrade-check", "-d", _DOMAIN, "--format", "json"]
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload == [_WARNING.as_dict()]

    def test_run_with_no_findings_exits_0(self, monkeypatch):
        monkeypatch.setattr(upgrade_cli, "run_upgrade_checks", lambda d: [])
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        assert result.exit_code == 0
        assert "READY" in result.stdout

    def test_unknown_option_exits_2_with_empty_stdout(self):
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN, "--bogus"])
        assert result.exit_code == 2
        assert result.stdout == ""

    def test_warning_code_differs_from_error_code(self, monkeypatch):
        monkeypatch.setattr(upgrade_cli, "run_upgrade_checks", lambda d: [_WARNING])
        warned = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        errored = runner.invoke(
            app, ["upgrade-check", "-d", _DOMAIN, "--format", "yaml"]
        )
        assert (warned.exit_code, errored.exit_code) == (1, 2)

    @pytest.mark.parametrize("fmt", ["rich", "json"])
    @pytest.mark.parametrize(
        ("args", "message"),
        [
            (["--pinned-version", "0.16"], "--pinned-version applies only with"),
            (
                ["--opportunities", "--pinned-version", "0.16latest"],
                "Invalid --pinned-version: '0.16latest'",
            ),
            (["-d", "nonexistent.module"], "Error loading Protean domain"),
            (
                ["-d", "nonexistent.module", "--opportunities"],
                "Error loading Protean domain",
            ),
        ],
    )
    def test_usage_error_exits_2_on_stderr(self, args, message, fmt):
        result = runner.invoke(
            app, ["upgrade-check", "-d", _TEXT_DOMAIN, *args, "--format", fmt]
        )
        assert result.exit_code == 2
        assert message in _stderr(result)
        assert result.stdout == ""

    @pytest.mark.parametrize("mode", [[], ["--opportunities"]])
    @pytest.mark.parametrize(
        ("source", "message"),
        [
            (
                "raise RuntimeError('boom')",
                "Error loading Protean domain: RuntimeError: boom",
            ),
            ("def broken(:", "Error loading Protean domain: SyntaxError"),
        ],
    )
    def test_domain_that_raises_at_import_exits_2(
        self, tmp_path, mode, source, message
    ):
        module = tmp_path / "broken_upgrade_domain.py"
        module.write_text(source, encoding="utf-8")
        result = runner.invoke(
            app, ["upgrade-check", "-d", str(module), *mode, "--format", "json"]
        )
        assert result.exit_code == 2
        assert message in _stderr(result)
        assert result.stdout == ""

    @pytest.mark.parametrize("fmt", ["rich", "json"])
    def test_domain_init_raising_exits_2(self, monkeypatch, fmt):
        def boom(self, *args, **kwargs):
            raise RuntimeError("adapters unreachable")

        monkeypatch.setattr(Domain, "init", boom)
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN, "--format", fmt])
        assert result.exit_code == 2
        assert "Error: adapters unreachable" in _stderr(result)
        assert result.stdout == ""

    def test_run_upgrade_checks_raising_exits_2(self, monkeypatch):
        def boom(domain):
            raise RuntimeError("checks blew up")

        monkeypatch.setattr(upgrade_cli, "run_upgrade_checks", boom)
        result = runner.invoke(
            app, ["upgrade-check", "-d", _DOMAIN, "--format", "json"]
        )
        assert result.exit_code == 2
        assert "Error: checks blew up" in _stderr(result)
        assert result.stdout == ""

    def test_run_opportunity_checks_raising_exits_2(self, monkeypatch):
        def boom(domain, pinned):
            raise RuntimeError("detectors blew up")

        monkeypatch.setattr(upgrade_cli, "run_opportunity_checks", boom)
        result = runner.invoke(
            app, ["upgrade-check", "-d", _TEXT_DOMAIN, "--opportunities"]
        )
        assert result.exit_code == 2
        assert "Error: detectors blew up" in _stderr(result)
        assert result.stdout == ""

    def test_an_exit_raised_by_the_checks_keeps_its_code(self, monkeypatch):
        def stop(domain):
            raise typer.Exit(code=7)

        monkeypatch.setattr(upgrade_cli, "run_upgrade_checks", stop)
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        assert result.exit_code == 7

    def test_help_lists_the_three_exit_codes(self):
        result = runner.invoke(app, ["upgrade-check", "--help"])
        assert result.exit_code == 0
        text = " ".join(result.stdout.split())
        assert "0: clean, or info findings only" in text
        assert "1: warning findings" in text
        assert "2: usage or environment error" in text


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
    def test_bad_pinned_version_exits_2(self, pinned):
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
        assert result.exit_code == 2
        assert "Invalid --pinned-version" in _stderr(result)
        assert result.stdout == ""

    def test_pinned_version_without_opportunities_exits_2(self):
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
        assert result.exit_code == 2
        assert "--pinned-version applies only with --opportunities" in _stderr(result)
        assert result.stdout == ""

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

    def test_a_failing_detector_surfaces_check_failed_and_exits_1(self, monkeypatch):
        # Detector findings are advisory, but a detector that cannot complete is
        # a CHECK_FAILED warning, and any warning exits 1 through the CLI.
        def boom(trees, pinned, domain):
            raise RuntimeError("detector blew up")

        monkeypatch.setattr(upgrade_opportunities, "_DETECTORS", (boom,))
        result = runner.invoke(
            app, ["upgrade-check", "-d", _TEXT_DOMAIN, "--opportunities"]
        )
        assert result.exit_code == 1
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
