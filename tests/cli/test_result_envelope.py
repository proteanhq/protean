"""Conformance tests for the shared CLI result envelope.

The envelope (``src/protean/cli/result.py``) is a versioned, guarded contract:
every command's ``--json`` output must validate against the pinned schema, put
exactly one JSON object on stdout, and keep logs/errors on stderr. These tests
pin the helper behaviour and run ``check`` and ``verify`` through each outcome
class, validating every ``--json`` payload against ``load_envelope_schema()``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate
from typer.testing import CliRunner

from protean.cli import app
from protean.cli.result import (
    ENVELOPE_VERSION,
    EXIT_FAILURE,
    EXIT_OK,
    EXIT_USAGE,
    build_envelope,
    load_envelope_schema,
)

# These build their own domains/projects; the autouse Test domain fixture would
# construct an unrelated Domain per test for nothing.
pytestmark = pytest.mark.no_test_domain

runner = CliRunner()

_CLEAN_DOMAIN = "tests/support/domains/test19/domain19.py:domain"
# A domain whose check reports warnings (findings failure).
_WARN_DOMAIN = "tests/support/domains/test25/domain25.py:domain"
# A domain with a structural error surfaced by ``check`` (findings failure).
_CHECK_ERR_DOMAIN = "tests/support/domains/test26/domain26.py:domain"

_PASSING_TEST = "def test_ok():\n    assert True\n"


@pytest.fixture(scope="module")
def schema() -> dict:
    """Load the CLI envelope JSON Schema once per module."""
    return load_envelope_schema()


def _sole_json_object(stdout: str) -> dict:
    """Decode ``stdout`` as exactly one JSON object with nothing trailing.

    Guards the "exactly one JSON object on stdout and nothing else" contract: a
    leaked log line before the object, or a second object after it, fails here.
    """
    decoder = json.JSONDecoder()
    obj, end = decoder.raw_decode(stdout.lstrip())
    assert stdout.lstrip()[end:].strip() == "", (
        f"stdout carried more than one JSON object:\n{stdout!r}"
    )
    assert isinstance(obj, dict), f"stdout was not a JSON object: {stdout!r}"
    return obj


# ---------------------------------------------------------------------------
# Helper unit cover
# ---------------------------------------------------------------------------


class TestEnvelopeHelpers:
    """``build_envelope``/``load_envelope_schema`` and the pinned constants."""

    def test_build_envelope_has_the_four_contract_keys(self):
        env = build_envelope(
            status="pass",
            data={"anything": 1},
            diagnostics=[],
        )
        assert env == {
            "version": ENVELOPE_VERSION,
            "status": "pass",
            "data": {"anything": 1},
            "diagnostics": [],
        }

    def test_build_envelope_copies_diagnostics(self):
        """A later mutation of the caller's list must not reach the envelope."""
        diags = [{"code": "X", "level": "warning", "message": "m"}]
        env = build_envelope(status="fail", data={}, diagnostics=diags)
        diags.append({"code": "Y", "level": "info", "message": "n"})
        assert len(env["diagnostics"]) == 1

    def test_exit_constants_are_the_convention(self):
        assert (EXIT_OK, EXIT_FAILURE, EXIT_USAGE) == (0, 1, 2)

    def test_a_built_envelope_validates(self, schema):
        env = build_envelope(
            status="fail",
            data={"detail": "here"},
            diagnostics=[{"code": "C", "level": "error", "message": "boom"}],
        )
        validate(env, schema)  # must not raise

    def test_missing_top_level_key_is_rejected(self, schema):
        """The schema is strict on the frame: drop ``data`` and it fails."""
        bad = {"version": "0.1.0", "status": "pass", "diagnostics": []}
        with pytest.raises(ValidationError):
            validate(bad, schema)

    def test_unknown_status_is_rejected(self, schema):
        bad = build_envelope(status="pass", data={}, diagnostics=[])
        bad["status"] = "warn"  # not in the enum
        with pytest.raises(ValidationError):
            validate(bad, schema)

    def test_extra_top_level_key_is_rejected(self, schema):
        """``additionalProperties: false`` on the frame: a 5th key fails."""
        bad = build_envelope(status="pass", data={}, diagnostics=[])
        bad["extra"] = "nope"
        with pytest.raises(ValidationError):
            validate(bad, schema)

    def test_non_object_data_is_rejected(self, schema):
        """``data`` must be an object — a scalar or a list fails."""
        bad = build_envelope(status="pass", data={}, diagnostics=[])
        bad["data"] = "not an object"
        with pytest.raises(ValidationError):
            validate(bad, schema)

    @pytest.mark.parametrize(
        "diag",
        [
            {"level": "error", "message": "m"},  # missing code
            {"code": "C", "message": "m"},  # missing level
            {"code": "C", "level": "error"},  # missing message
            {"code": "", "level": "error", "message": "m"},  # empty code
            {"code": "C", "level": "fatal", "message": "m"},  # bad level enum
        ],
    )
    def test_malformed_diagnostic_is_rejected(self, schema, diag):
        """The diagnostic ``$def`` is guarded too, not just the frame: a
        diagnostic missing a required field, with an empty ``code``, or an
        out-of-enum ``level`` fails validation."""
        bad = build_envelope(status="fail", data={}, diagnostics=[diag])
        with pytest.raises(ValidationError):
            validate(bad, schema)


# ---------------------------------------------------------------------------
# check --format json conformance
# ---------------------------------------------------------------------------


class TestCheckEnvelopeConformance:
    """``check --format json`` emits the envelope for every outcome class."""

    def test_clean_domain_validates_and_passes(self, schema):
        result = runner.invoke(app, ["check", "-d", _CLEAN_DOMAIN, "-f", "json"])
        assert result.exit_code == EXIT_OK
        env = _sole_json_object(result.stdout)
        validate(env, schema)
        assert env["status"] == "pass"
        # The check report is under ``data``.
        assert env["data"]["counts"]["errors"] == 0
        assert env["diagnostics"] == []

    def test_warn_domain_validates_and_fails(self, schema):
        result = runner.invoke(app, ["check", "-d", _WARN_DOMAIN, "-f", "json"])
        assert result.exit_code == EXIT_FAILURE
        env = _sole_json_object(result.stdout)
        validate(env, schema)
        assert env["status"] == "fail"
        # The diagnostics that caused the failure ride at the top level.
        assert len(env["diagnostics"]) > 0
        assert any(d["level"] == "warning" for d in env["diagnostics"])

    def test_error_domain_validates_and_fails(self, schema):
        result = runner.invoke(app, ["check", "-d", _CHECK_ERR_DOMAIN, "-f", "json"])
        assert result.exit_code == EXIT_FAILURE
        env = _sole_json_object(result.stdout)
        validate(env, schema)
        assert env["status"] == "fail"
        assert env["data"]["counts"]["errors"] > 0

    def test_load_failure_validates_with_error_status(self, schema):
        result = runner.invoke(app, ["check", "-d", "nonexistent.module", "-f", "json"])
        assert result.exit_code == EXIT_USAGE
        env = _sole_json_object(result.stdout)
        validate(env, schema)
        assert env["status"] == "error"
        # The error path emits the envelope, NOT a rich red line — stdout has no
        # markup and parses cleanly.
        assert "[red]" not in result.stdout
        assert "Error loading Protean domain" in env["data"]["error"]


# ---------------------------------------------------------------------------
# verify --json conformance
# ---------------------------------------------------------------------------


class TestVerifyEnvelopeConformance:
    """``verify --json`` emits the same envelope for every outcome class."""

    def _write_tests(self, tmp_path: Path, body: str) -> Path:
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        (tests_dir / "test_sample.py").write_text(body)
        return tests_dir

    def test_green_validates_and_passes(self, schema, tmp_path):
        tests_dir = self._write_tests(tmp_path, _PASSING_TEST)
        result = runner.invoke(
            app, ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir), "--json"]
        )
        assert result.exit_code == EXIT_OK
        env = _sole_json_object(result.stdout)
        validate(env, schema)
        assert env["status"] == "pass"
        assert env["data"]["verdict"] == "pass"

    def test_check_failure_validates_and_fails(self, schema, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app, ["verify", "-d", _WARN_DOMAIN, "--path", str(empty), "--json"]
        )
        assert result.exit_code == 4
        env = _sole_json_object(result.stdout)
        validate(env, schema)
        assert env["status"] == "fail"
        # The check-stage diagnostics surface at the envelope's top level.
        assert len(env["diagnostics"]) > 0

    def test_usage_error_validates_with_error_status(self, schema):
        result = runner.invoke(app, ["verify", "-d", "nonexistent.module", "--json"])
        assert result.exit_code == EXIT_USAGE
        env = _sole_json_object(result.stdout)
        validate(env, schema)
        assert env["status"] == "error"
        assert "[red]" not in result.stdout


# ---------------------------------------------------------------------------
# Clean stdout (the #1010 generalization)
# ---------------------------------------------------------------------------


class TestMachineOutputCleanStdout:
    """Machine output is exactly one JSON object on stdout. In human mode error
    text goes to stderr; under --json it is carried in the envelope alone, not
    printed to either stream. A domain that logs during check must not corrupt
    the payload."""

    def test_check_json_stdout_is_one_object_with_error_suppressed(self):
        result = runner.invoke(app, ["check", "-d", "nonexistent.module", "-f", "json"])
        # stdout parses as one object and nothing else.
        _sole_json_object(result.stdout)
        # The rich red line is suppressed under --json (it does not go to stdout
        # or stderr), so stdout is the sole envelope and carries no markup.
        assert "[red]" not in result.stdout

    def test_check_rich_load_error_goes_to_stderr_not_stdout(self):
        result = runner.invoke(app, ["check", "-d", "nonexistent.module"])
        assert result.exit_code == EXIT_USAGE
        # Human mode: the error is on stderr, stdout is empty.
        assert result.stdout.strip() == ""
        assert "Error loading Protean domain" in result.stderr

    def test_check_warn_json_stdout_is_pure(self):
        """A domain that emits diagnostics still puts one clean object on stdout
        (this is the path where init/check may log)."""
        result = runner.invoke(app, ["check", "-d", _WARN_DOMAIN, "-f", "json"])
        env = _sole_json_object(result.stdout)
        assert env["status"] == "fail"

    def test_check_json_stdout_clean_when_domain_logs(self, tmp_path, schema):
        """The #1010 generalization, exercised directly: a domain that emits a
        log line while ``protean check`` loads it must not corrupt the JSON
        envelope. The log lands on stderr (protean routes its console handler
        there); stdout stays exactly one envelope object."""
        marker = "LEAKY_LOG_LINE_1329"
        dom = tmp_path / "logging_domain.py"
        dom.write_text(
            "import structlog\n"
            "from protean import Domain\n"
            # Fires when `protean check` imports the domain module — the exact
            # kind of stray log #1010 was about.
            f'structlog.get_logger("test.leak").warning("{marker}")\n'
            'domain = Domain(name="LoggingDomain")\n'
        )
        result = runner.invoke(app, ["check", "-d", f"{dom}:domain", "-f", "json"])
        env = _sole_json_object(result.stdout)
        validate(env, schema)
        # The log must not have leaked onto the machine payload...
        assert marker not in result.stdout
        # ...and it must actually have fired (else this test asserts nothing):
        # it lands on stderr, which the runner captures separately.
        assert marker in result.stderr


# ---------------------------------------------------------------------------
# --log-config precedence (route_logs_to_stderr must not clobber it)
# ---------------------------------------------------------------------------


class TestRouteLogsToStderrRespectsLogConfig:
    """``route_logs_to_stderr`` calls ``configure_logging()`` unconditionally
    if left unguarded, which rebuilds the root logger's handlers and would
    silently discard a ``--log-config``/``--log-level``/``--log-format``
    configuration the CLI callback already applied. ``check`` and ``verify``
    read the ``CTX_LOG_CONFIGURED`` flag off the context and skip the call
    when it is set — the same guard ``server`` and ``observatory`` use."""

    @staticmethod
    def _log_config_path(tmp_path: Path) -> Path:
        path = tmp_path / "logconf.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "disable_existing_loggers": False,
                    "handlers": {"custom": {"class": "logging.NullHandler"}},
                    "root": {"handlers": ["custom"], "level": "DEBUG"},
                }
            )
        )
        return path

    def test_check_with_log_config_does_not_reconfigure(self, tmp_path, monkeypatch):
        import protean.utils.logging as logging_module

        calls = []
        monkeypatch.setattr(
            logging_module,
            "configure_logging",
            lambda *a, **kw: calls.append((a, kw)),
        )
        log_config = self._log_config_path(tmp_path)
        result = runner.invoke(
            app,
            [
                "--log-config",
                str(log_config),
                "check",
                "-d",
                "nonexistent.module",
                "-f",
                "json",
            ],
        )
        assert result.exit_code == EXIT_USAGE
        # The CLI callback's own call is bound at import time, so this spy only
        # observes route_logs_to_stderr's (lazily imported) call — it must not
        # fire when --log-config already configured logging.
        assert calls == []

    def test_verify_with_log_config_does_not_reconfigure(self, tmp_path, monkeypatch):
        import protean.utils.logging as logging_module

        calls = []
        monkeypatch.setattr(
            logging_module,
            "configure_logging",
            lambda *a, **kw: calls.append((a, kw)),
        )
        log_config = self._log_config_path(tmp_path)
        result = runner.invoke(
            app,
            [
                "--log-config",
                str(log_config),
                "verify",
                "-d",
                "nonexistent.module",
                "--json",
            ],
        )
        assert result.exit_code == EXIT_USAGE
        assert calls == []

    def test_verify_without_log_config_still_configures(self, monkeypatch):
        """The guard must not swallow the normal (no --log-config) case."""
        import protean.utils.logging as logging_module

        calls = []
        monkeypatch.setattr(
            logging_module,
            "configure_logging",
            lambda *a, **kw: calls.append((a, kw)),
        )
        result = runner.invoke(app, ["verify", "-d", "nonexistent.module", "--json"])
        assert result.exit_code == EXIT_USAGE
        assert len(calls) == 1
