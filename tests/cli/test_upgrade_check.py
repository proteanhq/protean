"""CLI smoke tests for ``protean upgrade-check``."""

import json
import sys

import pytest
import structlog
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
            ("import sys; sys.exit(0)", "Error loading Protean domain: SystemExit: 0"),
            ("import sys; sys.exit(1)", "Error loading Protean domain: SystemExit: 1"),
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
        assert "Error: RuntimeError: adapters unreachable" in _stderr(result)
        assert result.stdout == ""

    @pytest.mark.parametrize(
        ("error", "message"),
        [
            (SystemExit(0), "Error: SystemExit: 0"),
            (RuntimeError(), "Error: RuntimeError"),
        ],
    )
    def test_domain_init_exit_or_empty_error_exits_2(self, monkeypatch, error, message):
        # A sys.exit(0) during init must not read as a clean run, and an
        # exception with no message still names what failed.
        def boom(self, *args, **kwargs):
            raise error

        monkeypatch.setattr(Domain, "init", boom)
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        assert result.exit_code == 2
        assert _stderr(result).endswith(message)
        assert result.stdout == ""

    def test_no_domain_found_exits_2(self, tmp_path, monkeypatch):
        # With an empty --domain, discovery searches the working directory and
        # returns None when it finds nothing.
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["upgrade-check", "-d", ""])
        assert result.exit_code == 2
        assert "Error loading Protean domain: no domain found." in _stderr(result)
        assert result.stdout == ""

    def test_run_upgrade_checks_raising_exits_2(self, monkeypatch):
        def boom(domain):
            raise RuntimeError("checks blew up")

        monkeypatch.setattr(upgrade_cli, "run_upgrade_checks", boom)
        result = runner.invoke(
            app, ["upgrade-check", "-d", _DOMAIN, "--format", "json"]
        )
        assert result.exit_code == 2
        assert "Error: RuntimeError: checks blew up" in _stderr(result)
        assert result.stdout == ""

    def test_run_opportunity_checks_raising_exits_2(self, monkeypatch):
        def boom(domain, pinned):
            raise RuntimeError("detectors blew up")

        monkeypatch.setattr(upgrade_cli, "run_opportunity_checks", boom)
        result = runner.invoke(
            app, ["upgrade-check", "-d", _TEXT_DOMAIN, "--opportunities"]
        )
        assert result.exit_code == 2
        assert "Error: RuntimeError: detectors blew up" in _stderr(result)
        assert result.stdout == ""

    @pytest.mark.parametrize(
        ("raised", "message"),
        [(typer.Exit(code=0), "Error: Exit"), (typer.Abort(), "Error: Abort")],
    )
    def test_an_exit_raised_by_the_checks_exits_2(self, monkeypatch, raised, message):
        # Exit(0) would read as a clean run and Abort's 1 as warnings found.
        def stop(domain):
            raise raised

        monkeypatch.setattr(upgrade_cli, "run_upgrade_checks", stop)
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        assert result.exit_code == 2
        assert message in _stderr(result)
        assert result.stdout == ""

    def test_applies_the_domains_logging_settings(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            Domain, "configure_logging", lambda self, **kw: calls.append(kw)
        )
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        assert result.exit_code == 0
        assert calls == [{}]

    def test_cli_log_level_overrides_the_domains_level(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            Domain, "configure_logging", lambda self, **kw: calls.append(kw)
        )
        result = runner.invoke(
            app, ["--log-level", "DEBUG", "upgrade-check", "-d", _DOMAIN]
        )
        assert result.exit_code == 0
        assert calls == [{"level": "DEBUG"}]

    def test_a_logging_settings_error_exits_2(self, monkeypatch):
        def boom(self, **kw):
            raise ValueError("bad [logging]")

        monkeypatch.setattr(Domain, "configure_logging", boom)
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        assert result.exit_code == 2
        assert "Error: ValueError: bad [logging]" in _stderr(result)
        assert result.stdout == ""

    def test_a_logger_first_used_at_import_still_redacts(self, tmp_path, monkeypatch):
        # Production caching: the session fixture in tests/conftest.py turns
        # structlog's logger cache off, which would hide a stale chain.
        monkeypatch.setattr(structlog, "configure", structlog.configure.__wrapped__)
        module = tmp_path / "redacting_upgrade_domain.py"
        module.write_text(
            "from protean import Domain\n"
            "from protean.utils.logging import get_logger\n"
            "log = get_logger('redacting_upgrade_domain')\n"
            "log.info('domain.importing')\n"
            "domain = Domain(name='Redacting',"
            " config={'logging': {'redact': ['password']}})\n",
            encoding="utf-8",
        )

        def log_secret(domain):
            sys.modules["redacting_upgrade_domain"].log.warning(
                "domain.connecting", password="hunter2"
            )
            return []

        monkeypatch.setattr(upgrade_cli, "run_upgrade_checks", log_secret)
        result = runner.invoke(app, ["upgrade-check", "-d", str(module)])
        assert result.exit_code == 0
        assert "domain.connecting" in result.stderr
        assert "hunter2" not in result.stderr

    def test_markup_in_a_finding_prints_literally(self, monkeypatch):
        # A CHECK_FAILED detail can repeat a driver error that holds square
        # brackets; rich must print it, not parse it as a closing tag.
        finding = UpgradeFinding(
            code="CHECK_FAILED",
            level="warning",
            title="check [failed]",
            detail="could not connect to /var/run/[/x]sock",
            remediation="see [databases.default]",
            element="[databases.default]",
            sql="SELECT '[/dim]';",
        )
        monkeypatch.setattr(upgrade_cli, "run_upgrade_checks", lambda d: [finding])
        result = runner.invoke(app, ["upgrade-check", "-d", _DOMAIN])
        assert result.exit_code == 1
        assert "could not connect to /var/run/[/x]sock" in result.stdout
        assert "check [failed]" in result.stdout
        assert "see [databases.default]" in result.stdout
        assert "([databases.default])" in result.stdout
        assert "SELECT '[/dim]';" in result.stdout

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
        assert "Invalid --pinned-version" not in result.stderr

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

    def test_a_failing_detector_under_json_is_a_warning_and_exits_1(self, monkeypatch):
        def boom(trees, pinned, domain):
            raise RuntimeError("detector blew up")

        monkeypatch.setattr(upgrade_opportunities, "_DETECTORS", (boom,))
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
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        failed = [f for f in payload if f["code"] == "CHECK_FAILED"]
        assert len(failed) == 1
        assert failed[0]["level"] == "warning"


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
