"""Tests for the ``protean verify`` CLI command.

``verify`` composes init + check + tests into one verdict with a stable exit
code contract (the CLI-wide convention, with the stage classes pinned):

    0 — all green            3 — domain init failed
    2 — usage error          4 — check failed (bad [lint] config, or findings
    5 — tests failed             at or above the [lint].level floor)

Exit 2 covers verify's own usage errors: domain not found, or a ``--path`` that
is not a directory (Click's own default for a bad command line, too).

Under ``--json`` the result is the shared CLI envelope (see
``src/protean/cli/result.py``): ``{version, status, data, diagnostics}`` with
the verdict and stage tree under ``data``.

These tests exercise each exit code and the ``--json`` envelope. Most run
in-process with ``CliRunner`` against existing support domains and a throwaway
``pytest`` directory; one runs ``protean verify`` as a real subprocess against a
freshly generated scaffold — the end-to-end acceptance case the issue asks for.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.cli.verify import VerifyResult, run_verify

# These build their own domains/projects; the autouse Test domain fixture would
# construct an unrelated Domain per test for nothing.
pytestmark = pytest.mark.no_test_domain

runner = CliRunner()

# ``verify --json`` writes the envelope to stdout and every log line / warning to
# stderr, so a real ``protean verify --json | jq`` stays clean. Parse
# ``result.stdout`` (the pure stdout stream), never ``result.output`` — since
# click 8.2 the latter mixes stdout and stderr in write order, which interleaves
# the domain's init/check log lines into the JSON.

# A clean domain (inits + checks with no findings).
_CLEAN_DOMAIN = "tests/support/domains/test19/domain19.py:domain"
# A domain that inits cleanly but check reports warnings (status "warn").
_WARN_DOMAIN = "tests/support/domains/test25/domain25.py:domain"
# A domain whose check is info-only (status "info") — must NOT gate.
_INFO_DOMAIN = "tests/support/domains/test27/domain27.py:domain"
# A domain that fails during init() (identity-strategy misconfiguration).
_INIT_FAIL_DOMAIN = "tests/support/domains/test26/domain26.py:domain"
# A domain with warnings that opts out of warning gating via [lint].level="error".
_LEVEL_ERROR_DOMAIN = "tests/support/domains/test32/domain32.py:domain"
# A domain with an invalid [lint].level value.
_BAD_LEVEL_DOMAIN = "tests/support/domains/test34/domain34.py:domain"
# A domain with a malformed [lint].suppressions count (a string, not an int).
_BAD_SUPPRESSIONS_DOMAIN = "tests/support/domains/test36/domain36.py:domain"
# A domain whose [lint] is not a table at all (lint = 5).
_BAD_LINT_TABLE_DOMAIN = "tests/support/domains/test37/domain37.py:domain"
# A domain module that raises a bare RuntimeError on import — not the
# ImportError that locate_domain wraps in NoDomainException.
_IMPORT_RAISES_DOMAIN = "tests/support/domains/test40/domain40.py"
# A domain module whose own top-level `import` fails — the ImportError that
# locate_domain *does* wrap in NoDomainException, distinct from "module not
# found" (both raise NoDomainException, but only the latter is a usage error).
_NESTED_IMPORT_ERROR_DOMAIN = "tests/support/domains/test41/domain41.py"


def _write_test(directory: Path, body: str) -> Path:
    """Drop a single pytest file into ``directory`` and return the dir."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "test_sample.py").write_text(body)
    return directory


_PASSING_TEST = "def test_ok():\n    assert True\n"
_FAILING_TEST = "def test_bad():\n    assert False\n"


class TestVerifyGreen:
    """A clean domain with passing tests exits 0 with a pass verdict."""

    def test_green_project_exits_0(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["data"]["verdict"] == "pass"
        # No stage may report a failure on the green path (guards a vacuous pass).
        assert all(
            data["data"]["stages"][s]["status"] == "pass"
            for s in ("init", "check", "tests")
        )

    def test_json_envelope_has_settled_keys(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        data = json.loads(result.stdout)
        # Top-level envelope is the shared CLI frame.
        assert set(data.keys()) == {"version", "status", "data", "diagnostics"}
        assert data["version"] == "0.1.0"
        # Verify's own detail — verdict + stage tree — lives under ``data``.
        assert set(data["data"].keys()) == {"verdict", "stages"}
        assert set(data["data"]["stages"].keys()) == {"init", "check", "tests"}
        # Each stage carries its settled sub-keys.
        assert "status" in data["data"]["stages"]["init"]
        assert {"status", "counts", "diagnostics"} <= set(
            data["data"]["stages"]["check"]
        )
        assert {"status", "returncode", "passed", "failed"} <= set(
            data["data"]["stages"]["tests"]
        )
        assert data["data"]["stages"]["tests"]["passed"] == 1
        assert data["data"]["stages"]["tests"]["returncode"] == 0

    def test_human_table_names_each_stage(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir)],
        )
        assert result.exit_code == 0
        for stage in ("init", "check", "tests"):
            assert stage in result.stdout
        assert "Overall" in result.stdout
        assert "PASS" in result.stdout


class TestVerifyCheckFailure:
    """A domain with check warnings exits 4, independent of the tests stage."""

    def test_check_warnings_exit_4(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _WARN_DOMAIN, "--path", str(empty), "--json"],
        )
        assert result.exit_code == 4, result.output
        data = json.loads(result.stdout)
        assert data["data"]["verdict"] == "fail"
        assert data["data"]["stages"]["check"]["status"] == "fail"
        assert data["data"]["stages"]["check"]["counts"]["warnings"] > 0
        # The failing diagnostics are carried in the envelope.
        codes = {d["code"] for d in data["data"]["stages"]["check"]["diagnostics"]}
        assert "UNHANDLED_EVENT" in codes

    def test_check_failure_named_in_rich_output(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _WARN_DOMAIN, "--path", str(empty)],
        )
        assert result.exit_code == 4
        assert "FAIL" in result.stdout
        assert "UNHANDLED_EVENT" in result.stdout

    def test_info_only_domain_does_not_gate(self, tmp_path):
        """Info-only findings must NOT fail check — a green scaffold carrying a
        DEPRECATED_ELEMENT-style info diagnostic still passes."""
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _INFO_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["data"]["stages"]["check"]["status"] == "pass"
        # It really is info-only (proves the pass is not because it is clean).
        assert data["data"]["stages"]["check"]["counts"]["infos"] > 0
        assert data["data"]["stages"]["check"]["counts"]["warnings"] == 0


class TestVerifyTestFailure:
    """A clean domain with a failing test exits 5; check stays independent."""

    def test_failing_test_exits_5(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _FAILING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        assert result.exit_code == 5, result.output
        data = json.loads(result.stdout)
        assert data["data"]["verdict"] == "fail"
        assert data["data"]["stages"]["tests"]["status"] == "fail"
        assert data["data"]["stages"]["tests"]["returncode"] != 0
        assert data["data"]["stages"]["tests"]["failed"] == 1
        # Check passed — the codes are independent and precedence is right.
        assert data["data"]["stages"]["check"]["status"] == "pass"

    def test_check_failure_takes_precedence_over_test_failure(self, tmp_path):
        """When check AND tests both fail, the exit code is check's (4), not 5."""
        tests_dir = _write_test(tmp_path / "tests", _FAILING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _WARN_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        assert result.exit_code == 4, result.output
        data = json.loads(result.stdout)
        # Both stages record their failure even though check's code wins.
        assert data["data"]["stages"]["check"]["status"] == "fail"
        assert data["data"]["stages"]["tests"]["status"] == "fail"

    def test_human_table_shows_pytest_output_on_failure(self, tmp_path):
        """Without ``--json``, a failing test prints the tail of the pytest
        output under the stage table, so a human run is actionable and not just
        a FAIL label."""
        tests_dir = _write_test(tmp_path / "tests", _FAILING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir)],
        )
        assert result.exit_code == 5, result.output
        assert "pytest output:" in result.output


class TestVerifyNoTests:
    """An empty test directory (pytest returncode 5) is a pass, not a failure."""

    def test_no_tests_collected_is_pass(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(empty), "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["data"]["stages"]["tests"]["status"] == "pass"
        # The returncode is preserved so "no tests" is distinguishable.
        assert data["data"]["stages"]["tests"]["returncode"] == 5
        assert data["data"]["stages"]["tests"]["passed"] == 0


class TestVerifyLoadFailures:
    """Domain-not-found (usage, 2) and domain-init-failed (3) are distinct codes."""

    def test_domain_not_found_exits_2(self):
        result = runner.invoke(app, ["verify", "-d", "nonexistent.module"])
        assert result.exit_code == 2
        # The error line goes to stderr; the compact init row still names it on
        # stdout (result.output mixes both streams).
        assert "Error loading Protean domain" in result.stdout
        # A clean message, not a traceback.
        assert "Traceback" not in result.output

    def test_domain_not_found_json_envelope(self):
        result = runner.invoke(app, ["verify", "-d", "nonexistent.module", "--json"])
        assert result.exit_code == 2
        data = json.loads(result.stdout)
        # A usage error is envelope status "error".
        assert data["status"] == "error"
        assert data["data"]["verdict"] == "fail"
        assert data["data"]["stages"]["init"]["status"] == "fail"
        # The human-facing message survives in the JSON payload — an agent reads
        # it from data.stages.init.error, not from the (stderr) red line. This is
        # the JSON error payload that matters most to a consumer, so pin it.
        assert "Error loading Protean domain" in data["data"]["stages"]["init"]["error"]
        # Check and tests never ran.
        assert data["data"]["stages"]["check"]["status"] == "skipped"
        assert data["data"]["stages"]["tests"]["status"] == "skipped"
        # The init stage already carries the message; data.error is reserved for
        # a usage error caught before any stage ran, so it is not duplicated here.
        assert "error" not in data["data"]

    def test_init_failure_json_envelope_carries_error(self):
        """A found-but-broken domain (init failure, exit 3) carries its message
        under data.stages.init.error in the JSON envelope, with status "fail"."""
        result = runner.invoke(app, ["verify", "-d", _INIT_FAIL_DOMAIN, "--json"])
        assert result.exit_code == 3, result.output
        data = json.loads(result.stdout)
        assert data["status"] == "fail"
        assert data["data"]["stages"]["init"]["status"] == "fail"
        assert "Domain failed to initialize" in data["data"]["stages"]["init"]["error"]

    def test_init_failure_exits_3(self):
        result = runner.invoke(app, ["verify", "-d", _INIT_FAIL_DOMAIN])
        assert result.exit_code == 3
        assert "Domain failed to initialize" in result.stdout
        assert "Traceback" not in result.output

    def test_init_failure_is_distinct_from_not_found(self):
        """A found-but-broken domain is 3; a missing one is 2."""
        found_broken = runner.invoke(app, ["verify", "-d", _INIT_FAIL_DOMAIN])
        missing = runner.invoke(app, ["verify", "-d", "nonexistent.module"])
        assert found_broken.exit_code == 3
        assert missing.exit_code == 2
        assert found_broken.exit_code != missing.exit_code

    def test_domain_module_import_error_exits_3(self):
        """A domain module that fails to import with something other than
        ``ImportError`` (here, a plain ``RuntimeError``) is a load failure (3),
        not an unhandled traceback and not the domain-not-found usage error (2)."""
        result = runner.invoke(app, ["verify", "-d", _IMPORT_RAISES_DOMAIN])
        assert result.exit_code == 3, result.output
        assert "Domain failed to initialize" in result.stdout
        assert "Traceback" not in result.output

    def test_domain_module_import_error_json_envelope(self):
        result = runner.invoke(app, ["verify", "-d", _IMPORT_RAISES_DOMAIN, "--json"])
        assert result.exit_code == 3
        data = json.loads(result.stdout)
        # An init failure is a detected failure — envelope status "fail".
        assert data["status"] == "fail"
        assert data["data"]["verdict"] == "fail"
        assert data["data"]["stages"]["init"]["status"] == "fail"
        assert data["data"]["stages"]["check"]["status"] == "skipped"
        assert data["data"]["stages"]["tests"]["status"] == "skipped"

    def test_nested_import_error_exits_3_not_2(self):
        """A domain module found on disk, but whose own top-level ``import``
        fails, is a load failure (3) — even though ``locate_domain`` raises
        the same ``NoDomainException`` it uses for "module not found" (2)."""
        result = runner.invoke(app, ["verify", "-d", _NESTED_IMPORT_ERROR_DOMAIN])
        assert result.exit_code == 3, result.output
        assert "Error loading Protean domain" in result.stdout
        assert "While importing" in result.stdout

    def test_nested_import_error_json_envelope(self):
        result = runner.invoke(
            app, ["verify", "-d", _NESTED_IMPORT_ERROR_DOMAIN, "--json"]
        )
        assert result.exit_code == 3
        data = json.loads(result.stdout)
        assert data["data"]["verdict"] == "fail"
        assert data["data"]["stages"]["init"]["status"] == "fail"
        assert data["data"]["stages"]["check"]["status"] == "skipped"
        assert data["data"]["stages"]["tests"]["status"] == "skipped"

    def test_nested_import_error_table_row_is_single_line(self):
        """The multi-line ``While importing ...`` message (it embeds a full
        ``traceback.format_exc()``) is already printed in full above the
        table; the compact ``init`` row must collapse it to its first line
        instead of reproducing the traceback and breaking the table layout."""
        result = runner.invoke(app, ["verify", "-d", _NESTED_IMPORT_ERROR_DOMAIN])
        assert result.exit_code == 3, result.output
        table_lines = [
            line
            for line in result.stdout.splitlines()
            if line.strip().startswith("init")
        ]
        assert len(table_lines) == 1
        assert "Traceback" not in table_lines[0]


class TestVerifyLintConfig:
    """A malformed ``[lint]`` config must fail check (exit 4), not read as a
    false green. ``verify`` calls ``Domain.check()`` directly, whose IR build
    swallows the ``ConfigurationError`` a bad ``[lint]`` block raises, so verify
    runs the same config validation ``protean check`` does."""

    def test_bad_suppressions_count_exits_4(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _BAD_SUPPRESSIONS_DOMAIN, "--path", str(empty), "--json"],
        )
        assert result.exit_code == 4, result.output
        data = json.loads(result.stdout)
        assert data["data"]["verdict"] == "fail"
        assert data["data"]["stages"]["check"]["status"] == "fail"
        # The config error is surfaced as a check error (not swallowed).
        messages = " ".join(
            e["message"] for e in data["data"]["stages"]["check"]["errors"]
        )
        assert "[lint].suppressions" in messages
        assert "non-negative integer" in messages

    def test_bad_suppressions_named_in_rich_output(self, tmp_path):
        """The check-error rendering branch (``✗ {message}``) is exercised."""
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _BAD_SUPPRESSIONS_DOMAIN, "--path", str(empty)],
        )
        assert result.exit_code == 4
        assert "[lint].suppressions" in result.stdout

    def test_non_table_lint_exits_4(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _BAD_LINT_TABLE_DOMAIN, "--path", str(empty), "--json"],
        )
        assert result.exit_code == 4, result.output
        data = json.loads(result.stdout)
        messages = " ".join(
            e["message"] for e in data["data"]["stages"]["check"]["errors"]
        )
        assert "[lint]" in messages
        assert "must be a table" in messages

    def test_invalid_lint_level_exits_4(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _BAD_LEVEL_DOMAIN, "--path", str(empty), "--json"],
        )
        assert result.exit_code == 4, result.output
        data = json.loads(result.stdout)
        messages = " ".join(
            e["message"] for e in data["data"]["stages"]["check"]["errors"]
        )
        assert "[lint].level" in messages


_COMMAND_VERBS_DOMAIN = """
from protean import Domain
from protean.fields import String

domain = Domain()
domain.config["lint"]["command_verbs"] = {verbs!r}


@domain.aggregate
class Stock:
    title = String()
"""


class TestVerifyCommandVerbsConfig:
    @pytest.mark.parametrize(
        "index, bad", list(enumerate(["adjust", [1], [""], ["void-it"]]))
    )
    def test_bad_command_verbs_exit_4(self, tmp_path, index, bad):
        domain_file = tmp_path / f"verify_command_verbs_{index}_1872.py"
        domain_file.write_text(_COMMAND_VERBS_DOMAIN.format(verbs=bad))
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", str(domain_file), "--path", str(empty), "--json"],
        )
        assert result.exit_code == 4, result.output
        errors = json.loads(result.stdout)["data"]["stages"]["check"]["errors"]
        assert [e["code"] for e in errors] == ["INVALID_LINT_CONFIG"]
        assert errors[0]["message"] == (
            "[lint].command_verbs must be a list of non-empty alphabetic words, "
            f"got {bad!r}."
        )


class TestVerifyLintLevel:
    """The check stage honours ``[lint].level`` (default ``warn``), the same
    severity floor ``protean check`` uses — it does not hardcode the warn floor."""

    def test_level_error_opts_out_of_warning_gating(self, tmp_path):
        """A domain with warnings but ``[lint].level="error"`` passes check —
        only errors gate. With the warn floor hardcoded, this would exit 4."""
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _LEVEL_ERROR_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["data"]["stages"]["check"]["status"] == "pass"
        # It really does carry warnings — the pass is because level="error", not
        # because the domain is clean.
        assert data["data"]["stages"]["check"]["counts"]["warnings"] > 0


class TestVerifyInternals:
    """Unit cover for the defensive helpers whose branches no end-to-end path
    reaches: an error-severity finding gates regardless of ``[lint].level``, and
    an unexpected ``Domain.check()`` crash is contracted to a check failure
    (exit 4) rather than a traceback. The re-run inside ``check()`` has no known
    concrete trigger, so it can only be exercised directly."""

    def test_errors_gate_even_at_error_level(self):
        from protean.cli.verify import _check_gates

        assert _check_gates({"errors": 1, "warnings": 0, "infos": 0}, "error") is True

    def test_check_crash_is_surfaced_as_exit_4(self):
        from protean.cli.verify import _run_check

        class _BoomDomain:
            config: dict = {}

            def check(self):
                raise RuntimeError("kaboom")

        check_failed, stage = _run_check(_BoomDomain())

        assert check_failed is True
        assert stage["status"] == "fail"
        assert stage["errors"][0]["code"] == "CHECK_FAILED"
        assert "kaboom" in stage["errors"][0]["message"]


class TestVerifyTestCounts:
    """The pass/fail counts come from pytest's final summary line, not from the
    first "<N> passed" / "<N> failed" text anywhere in the output."""

    def _tests_stage(self, tests_dir: Path) -> tuple[int, dict[str, Any]]:
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        return result.exit_code, json.loads(result.stdout)["data"]["stages"]["tests"]

    def test_number_in_failure_message_is_not_the_failed_count(self, tmp_path):
        body = (
            "def test_db():\n"
            "    raise AssertionError("
            "'connection to server on port 15432 failed')\n"
        )
        tests_dir = _write_test(tmp_path / "tests", body)

        exit_code, stage = self._tests_stage(tests_dir)

        assert exit_code == 5
        assert stage["failed"] == 1
        assert stage["passed"] == 0
        assert stage["status"] == "fail"
        assert stage["returncode"] == 1

    def test_skip_reason_is_not_the_passed_count(self, tmp_path):
        from protean.cli.verify import _run_tests

        body = (
            "import pytest\n\n"
            "def test_ok():\n"
            "    assert True\n\n"
            "@pytest.mark.skip(reason='0 passed on this platform')\n"
            "def test_skipped():\n"
            "    pass\n"
        )
        tests_dir = _write_test(tmp_path / "tests", body)
        (tests_dir / "pytest.ini").write_text("[pytest]\naddopts = -ra\n")

        # The skip reason must reach the output, or this test proves nothing.
        _, output = _run_tests(str(tests_dir), "test")
        assert "0 passed on this platform" in output

        exit_code, stage = self._tests_stage(tests_dir)

        assert exit_code == 0
        assert stage["passed"] == 1
        assert stage["failed"] == 0
        assert stage["status"] == "pass"
        assert stage["returncode"] == 0

    def test_the_child_run_keeps_the_default_order(self, tmp_path):
        body = (
            "def test_randomly_is_off(pytestconfig):\n"
            "    assert not pytestconfig.pluginmanager.hasplugin('randomly')\n"
        )
        tests_dir = _write_test(tmp_path / "tests", body)
        (tests_dir / "pytest.ini").write_text("[pytest]\naddopts = -ra\n")

        exit_code, stage = self._tests_stage(tests_dir)

        assert exit_code == 0
        assert stage["passed"] == 1

    def test_one_pass_and_one_fail(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST + _FAILING_TEST)

        exit_code, stage = self._tests_stage(tests_dir)

        assert exit_code == 5
        assert stage["passed"] == 1
        assert stage["failed"] == 1
        assert stage["status"] == "fail"
        assert stage["returncode"] == 1

    def test_project_quiet_addopts_still_prints_the_summary(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST + _FAILING_TEST)
        (tests_dir / "pytest.ini").write_text("[pytest]\naddopts = -q\n")

        exit_code, stage = self._tests_stage(tests_dir)

        assert exit_code == 5
        assert stage["passed"] == 1
        assert stage["failed"] == 1
        assert stage["returncode"] == 1

    def test_summary_shaped_stderr_line_is_ignored(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        (tests_dir / "conftest.py").write_text(
            "import sys\n\n"
            "def pytest_unconfigure(config):\n"
            "    sys.stderr.write('9 passed in 1s\\n')\n"
        )

        exit_code, stage = self._tests_stage(tests_dir)

        assert exit_code == 0
        assert stage["passed"] == 1
        assert stage["failed"] == 0

    def test_later_stdout_line_ending_in_seconds_is_not_the_summary(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        (tests_dir / "conftest.py").write_text(
            "def pytest_unconfigure(config):\n    print('Finished in 3s')\n"
        )

        exit_code, stage = self._tests_stage(tests_dir)

        assert exit_code == 0
        assert stage["passed"] == 1
        assert stage["failed"] == 0

    @pytest.mark.parametrize(
        ("stdout", "expected"),
        [
            ("===== 2 failed, 3 passed in 0.12s =====\n", (3, 2)),
            ("1 passed in 0.07s\nFinished in 3s\n", (1, 0)),
            ("3 passed in 86401.00s (1 day, 0:00:01)\n", (3, 0)),
            ("1 failed, 1 passed in 0.01s\n", (1, 1)),
            ("==== 4 passed in 62.00s (0:01:02) ====\n", (4, 0)),
            ("no tests ran in 0.01s\n", (0, 0)),
            ("1 error in 0.10s\n", (0, 0)),
            ("collecting ...\nsomething went wrong\n", (0, 0)),
            ("", (0, 0)),
            ("1 passed, 2 xfailed in 0.1s\n", (1, 0)),
            ("1 passed, 1 xpassed in 0.1s\n", (1, 0)),
            (
                (
                    "FAILED test_x.py::test_a - 99 failed\n"
                    "SKIPPED [1] test_x.py:3: 0 passed\n"
                    "1 failed, 7 passed in 0.20s\n"
                ),
                (7, 1),
            ),
            (
                (
                    "\x1b[31m\x1b[1m1 failed\x1b[0m, \x1b[32m5 passed\x1b[0m"
                    "\x1b[31m in 0.10s\x1b[0m\n"
                ),
                (5, 1),
            ),
        ],
    )
    def test_parse_counts_reads_the_summary_line(self, stdout, expected):
        from protean.cli.verify import _parse_counts

        assert _parse_counts(stdout) == expected


class TestVerifyUsageErrors:
    """``verify``'s own usage errors exit 2 with a clean message, no traceback."""

    def test_path_not_a_directory_exits_2(self, tmp_path):
        missing = tmp_path / "does" / "not" / "exist"
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(missing), "--json"],
        )
        assert result.exit_code == 2, result.output
        assert "Traceback" not in result.output
        data = json.loads(result.stdout)
        # A usage error is envelope status "error".
        assert data["status"] == "error"
        assert data["data"]["verdict"] == "fail"
        # Nothing ran — every stage is skipped.
        assert all(
            data["data"]["stages"][s]["status"] == "skipped"
            for s in ("init", "check", "tests")
        )
        # No stage carries this error (nothing ran), so it lands on data.error —
        # otherwise a --json consumer would have only the bare exit code to go on.
        assert "--path is not a directory" in data["data"]["error"]

    def test_path_is_a_file_exits_2(self, tmp_path):
        a_file = tmp_path / "not_a_dir.txt"
        a_file.write_text("hi")
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(a_file)],
        )
        assert result.exit_code == 2
        assert "Traceback" not in result.output
        # The clean usage message, which only the up-front guard emits — an
        # unguarded subprocess would raise NotADirectoryError instead. It goes
        # to stderr so stdout stays clean; the stage table (all SKIPPED) is the
        # only thing on stdout.
        assert "--path is not a directory" in result.stderr
        assert "--path is not a directory" not in result.stdout

    def test_empty_domain_arg_exits_2(self, tmp_path, monkeypatch):
        """``-d ""`` with PROTEAN_DOMAIN unset is domain-not-found (exit 2),
        not an uncaught AssertionError.

        With an empty ``--domain`` and no ``PROTEAN_DOMAIN``, ``derive_domain``
        falls back to discovering a ``domain.py`` from the working directory and
        ``sys.path``. Other CLI tests chdir into a support project (e.g. test10,
        which has a ``domain.py``) and never restore ``sys.path``/``sys.modules``,
        so a discoverable ``domain`` module can linger and make this find a real
        domain instead of nothing. Isolate discovery: run from an empty dir, drop
        any cached ``domain``/``subdomain`` module, and hide the ``sys.path``
        entries that carry one. ``monkeypatch`` restores all of it afterwards.
        """
        monkeypatch.delenv("PROTEAN_DOMAIN", raising=False)
        monkeypatch.chdir(tmp_path)
        for name in ("domain", "subdomain"):
            monkeypatch.delitem(sys.modules, name, raising=False)
        clean_path = [
            entry
            for entry in sys.path
            if not (
                os.path.isfile(os.path.join(entry or ".", "domain.py"))
                or os.path.isfile(os.path.join(entry or ".", "subdomain.py"))
            )
        ]
        monkeypatch.setattr(sys, "path", clean_path)

        result = runner.invoke(
            app,
            ["verify", "-d", "", "--path", str(tmp_path)],
        )
        assert result.exit_code == 2
        assert "Traceback" not in result.output
        assert "No domain found" in result.stdout

    def test_bracketed_domain_name_survives_rich_markup(self):
        """A domain-not-found message that itself contains ``[...]`` (e.g. the
        module name echoed back in the error) must reach the user intact — both
        in the early ``[red]...[/red]`` line (now on stderr) and the compact
        table row (on stdout). Unescaped, ``rich`` treats ``[bogus]`` as a
        markup tag and strips it."""
        result = runner.invoke(app, ["verify", "-d", "[bogus]"])
        assert result.exit_code == 2
        # Table row on stdout, early error line on stderr — the bracketed name
        # survives markup in both.
        assert "Could not import '[bogus]'" in result.stdout
        assert "[bogus]" in result.stderr
        assert result.output.count("[bogus]") == 2  # early error line + table row


class TestVerifySubprocessEnv:
    """The tests stage runs pytest in a child process; ``verify`` scrubs a few
    parent env vars and puts a ``src/`` layout on the path. These are behaviours
    a consumer relies on, so they are pinned directly."""

    def test_parent_env_vars_are_scrubbed_from_child(self, tmp_path, monkeypatch):
        """VIRTUAL_ENV/PROTEAN_ENV/PROTEAN_DEBUG set in the parent must not reach
        the child pytest — a leaked VIRTUAL_ENV in particular can point tests at
        the wrong source tree."""
        monkeypatch.setenv("VIRTUAL_ENV", "/tmp/bogus-venv-should-not-leak")
        monkeypatch.setenv("PROTEAN_ENV", "leaked")
        monkeypatch.setenv("PROTEAN_DEBUG", "1")
        # PROTEAN_ENV is not dropped but replaced: the child gets ``--env``.
        body = (
            "import os\n"
            "def test_env_scrubbed():\n"
            "    assert 'VIRTUAL_ENV' not in os.environ\n"
            "    assert 'PROTEAN_DEBUG' not in os.environ\n"
            "    assert os.environ.get('PROTEAN_ENV') == 'memory'\n"
        )
        tests_dir = _write_test(tmp_path / "tests", body)
        result = runner.invoke(
            app,
            [
                "verify",
                "-d",
                _CLEAN_DOMAIN,
                "--path",
                str(tests_dir),
                "--env",
                "memory",
                "--json",
            ],
        )
        # If verify did not scrub the vars, the child test asserts False → the
        # tests stage fails → exit 4.
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["data"]["stages"]["tests"]["status"] == "pass"
        assert data["data"]["stages"]["tests"]["passed"] == 1

    def test_src_layout_is_importable_in_child(self, tmp_path):
        """A ``src/``-layout project that is not installed still has its ``src``
        put on the child's PYTHONPATH, so its own tests import the package. The
        package name is unique so the import can only succeed via the prepend."""
        project = tmp_path / "proj"
        pkg = project / "src" / "verify_srclayout_pkg"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text("")
        (pkg / "thing.py").write_text("VALUE = 42\n")
        body = (
            "from verify_srclayout_pkg.thing import VALUE\n"
            "def test_import_from_src():\n"
            "    assert VALUE == 42\n"
        )
        _write_test(project / "tests", body)
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(project), "--json"],
        )
        # Without the src prepend the import fails → collection error → exit 4.
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["data"]["stages"]["tests"]["status"] == "pass"
        assert data["data"]["stages"]["tests"]["passed"] == 1


_ENV_RECORDING_DOMAIN = """\
import os
from pathlib import Path

from protean import Domain

Path(__file__).with_suffix(".env").write_text(os.environ.get("PROTEAN_ENV", "<unset>"))

domain = Domain(name="EnvRecording")
"""


def _write_env_recording_domain(tmp_path: Path) -> tuple[str, Path]:
    """Write a domain module that records the ``PROTEAN_ENV`` it was imported
    under, and return its ``--domain`` spec and the record file.

    The module name is unique per test so an earlier import cached in
    ``sys.modules`` cannot stand in for this one."""
    module_name = f"verify_env_domain_{tmp_path.name.replace('-', '_')}"
    module = tmp_path / f"{module_name}.py"
    module.write_text(_ENV_RECORDING_DOMAIN)
    return f"{module}:domain", module.with_suffix(".env")


def _child_env_test(expected: str) -> str:
    return (
        "import os\n"
        "def test_child_env():\n"
        f"    assert os.environ['PROTEAN_ENV'] == {expected!r}\n"
    )


class TestVerifyEnv:
    """All three stages run under the one environment ``--env`` names (default
    ``test``): init and check see it as ``PROTEAN_ENV`` in this process, and the
    pytest child gets the same value. The caller's ``PROTEAN_ENV`` is put back."""

    def test_env_option_applies_to_init_and_tests(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PROTEAN_ENV", raising=False)
        domain, record = _write_env_recording_domain(tmp_path)
        tests_dir = _write_test(tmp_path / "tests", _child_env_test("memory"))
        result = runner.invoke(
            app,
            [
                "verify",
                "-d",
                domain,
                "--path",
                str(tests_dir),
                "--env",
                "memory",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        assert record.read_text() == "memory"
        data = json.loads(result.stdout)
        assert data["data"]["stages"]["tests"]["passed"] == 1

    def test_shell_exported_env_is_ignored(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROTEAN_ENV", "memory")
        domain, record = _write_env_recording_domain(tmp_path)
        tests_dir = _write_test(tmp_path / "tests", _child_env_test("test"))
        result = runner.invoke(
            app,
            ["verify", "-d", domain, "--path", str(tests_dir), "--json"],
        )
        assert result.exit_code == 0, result.output
        assert record.read_text() == "test"
        data = json.loads(result.stdout)
        assert data["data"]["stages"]["tests"]["passed"] == 1
        assert os.environ["PROTEAN_ENV"] == "memory"

    def test_callers_env_is_restored(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PROTEAN_ENV", "prior")
        domain, record = _write_env_recording_domain(tmp_path)
        tests_dir = _write_test(tmp_path / "tests", _child_env_test("memory"))
        result = run_verify(domain, str(tests_dir), env="memory")
        assert result.exit_code == 0, result.tests_output
        assert record.read_text() == "memory"
        assert os.environ["PROTEAN_ENV"] == "prior"

    def test_absent_env_stays_absent(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PROTEAN_ENV", raising=False)
        domain, record = _write_env_recording_domain(tmp_path)
        tests_dir = _write_test(tmp_path / "tests", _child_env_test("memory"))
        result = run_verify(domain, str(tests_dir), env="memory")
        assert result.exit_code == 0, result.tests_output
        assert record.read_text() == "memory"
        assert "PROTEAN_ENV" not in os.environ

    def test_already_imported_domain_keeps_its_first_env(self, tmp_path, monkeypatch):
        """A second call reuses the domain module already in ``sys.modules``, so
        init and check keep the first call's config. The tests stage still runs
        under the second call's ``env``."""
        monkeypatch.delenv("PROTEAN_ENV", raising=False)
        domain, record = _write_env_recording_domain(tmp_path)
        first = run_verify(
            domain,
            str(_write_test(tmp_path / "first", _child_env_test("memory"))),
            env="memory",
        )
        assert first.exit_code == 0, first.tests_output
        second = run_verify(
            domain,
            str(_write_test(tmp_path / "second", _child_env_test("other"))),
            env="other",
        )
        assert second.exit_code == 0, second.tests_output
        assert record.read_text() == "memory"
        assert second.stages["tests"]["passed"] == 1

    @pytest.mark.parametrize(
        "domain, code",
        [(_INIT_FAIL_DOMAIN, 3), ("no_such_module_for_verify_env", 2)],
        ids=["init-fails", "domain-not-found"],
    )
    @pytest.mark.parametrize("prior", ["prior", None], ids=["present", "absent"])
    def test_env_is_restored_on_early_return(
        self, tmp_path, monkeypatch, domain, code, prior
    ):
        if prior is None:
            monkeypatch.delenv("PROTEAN_ENV", raising=False)
        else:
            monkeypatch.setenv("PROTEAN_ENV", prior)
        result = run_verify(domain, str(tmp_path), env="memory")
        assert result.exit_code == code
        assert os.environ.get("PROTEAN_ENV") == prior

    def test_env_is_restored_when_a_stage_raises(self, tmp_path, monkeypatch):
        """An exception escaping a stage still puts the caller's value back."""
        monkeypatch.setenv("PROTEAN_ENV", "prior")
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        verify_module = sys.modules["protean.cli.verify"]

        def exploding_run_tests(path: str, env: str) -> Any:
            assert os.environ["PROTEAN_ENV"] == "memory"
            raise RuntimeError("tests stage blew up")

        monkeypatch.setattr(verify_module, "_run_tests", exploding_run_tests)
        with pytest.raises(RuntimeError, match="tests stage blew up"):
            run_verify(_CLEAN_DOMAIN, str(tests_dir), env="memory")
        assert os.environ["PROTEAN_ENV"] == "prior"

    def test_env_beats_protean_env_in_pytest_options(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PROTEAN_ENV", raising=False)
        monkeypatch.setenv("PYTEST_ADDOPTS", "-p no:randomly --protean-env memory")
        tests_dir = _write_test(tmp_path / "tests", _child_env_test("test"))
        (tests_dir / "pytest.ini").write_text(
            "[pytest]\naddopts = --protean-env memory\n"
        )
        result = run_verify(_CLEAN_DOMAIN, str(tests_dir))
        assert result.exit_code == 0, result.tests_output
        assert result.stages["tests"]["passed"] == 1

    def test_surrounding_spaces_are_stripped_from_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PROTEAN_ENV", raising=False)
        domain, record = _write_env_recording_domain(tmp_path)
        tests_dir = _write_test(tmp_path / "tests", _child_env_test("memory"))
        result = run_verify(domain, str(tests_dir), env=" memory ")
        assert result.exit_code == 0, result.tests_output
        assert record.read_text() == "memory"
        assert result.stages["tests"]["passed"] == 1

    @pytest.mark.parametrize("blank", ["", "  "], ids=["empty", "whitespace"])
    def test_blank_env_is_a_usage_error(self, tmp_path, monkeypatch, blank):
        monkeypatch.setenv("PROTEAN_ENV", "prior")
        domain, record = _write_env_recording_domain(tmp_path)
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        result = runner.invoke(
            app,
            [
                "verify",
                "-d",
                domain,
                "--path",
                str(tests_dir),
                "--env",
                blank,
                "--json",
            ],
        )
        assert result.exit_code == 2, result.output
        data = json.loads(result.stdout)
        assert data["status"] == "error"
        assert data["data"]["error"] == "--env must not be blank"
        # Rejected before init: the domain module was never imported.
        assert not record.exists()
        assert os.environ["PROTEAN_ENV"] == "prior"


def _generate_scaffold(tmp_path: Path) -> Path:
    """Generate a default project with ``protean new`` and return its root."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    result = runner.invoke(
        app,
        ["new", "scaffolded", "-o", str(out), "--defaults", "--skip-setup"],
    )
    assert result.exit_code == 0, f"protean new failed: {result.output}"
    return out / "scaffolded"


def _subprocess_env(project: Path) -> dict[str, str]:
    """Env for running the uninstalled generated project (src on PYTHONPATH,
    VIRTUAL_ENV/PROTEAN_ENV dropped), mirroring the scaffold test harness."""
    src = str(project / "src")
    existing = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "PYTHONPATH": src + os.pathsep + existing if existing else src,
    }
    env.pop("VIRTUAL_ENV", None)
    env.pop("PROTEAN_ENV", None)
    env.pop("PROTEAN_DEBUG", None)
    return env


def _parse_verify_json(stdout: str) -> dict[str, Any]:
    """Parse the JSON envelope printed by ``protean verify --json``.

    ``verify`` emits the envelope via ``typer.echo`` to stdout. Locate the
    first ``{`` and decode only that JSON object, ignoring any stray output
    before or after it (e.g. warnings or extra prints that end up on
    stdout instead of stderr).
    """
    start = stdout.find("{")
    assert start != -1, f"no JSON object in verify stdout:\n{stdout}"
    try:
        envelope, _ = json.JSONDecoder().raw_decode(stdout, start)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"invalid JSON envelope from verify:\n{stdout}") from exc
    assert isinstance(envelope, dict), (
        f"verify JSON envelope must be an object, got {type(envelope).__name__}: "
        f"{stdout}"
    )
    return envelope


class TestVerifyOnRealScaffold:
    """End-to-end: `protean verify` on a freshly generated project passes.

    Runs as a real subprocess (like the scaffold-start tests) so init, check,
    and the project's own pytest suite all run against the generated tree.
    """

    def test_scaffold_verifies_green(self, tmp_path):
        project = _generate_scaffold(tmp_path)

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "protean",
                "verify",
                "-d",
                "src/scaffolded/domain.py:scaffolded",
                "--path",
                ".",
                "--json",
            ],
            cwd=project,
            env=_subprocess_env(project),
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )

        assert completed.returncode == 0, (
            "`protean verify` must pass on a freshly generated project:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
        envelope = _parse_verify_json(completed.stdout)
        assert envelope["status"] == "pass"
        stages = envelope["data"]["stages"]
        assert envelope["data"]["verdict"] == "pass"
        for stage in ("init", "check", "tests"):
            assert stages[stage]["status"] == "pass", (
                f"`protean verify` stage {stage!r} must pass: {envelope}"
            )
        assert stages["tests"]["returncode"] == 0
        # The scaffold ships passing tests; verify actually ran them.
        assert stages["tests"]["passed"] >= 1, (
            "`protean verify` must run at least one real test, not report "
            f"green on an empty suite: {envelope}"
        )


class TestRunVerifyCore:
    """``run_verify`` computes the same verdict and exit code the command emits,
    but returns a ``VerifyResult`` instead of printing or raising ``typer.Exit``.
    This is the callable core ``protean new --from-model`` composes; the command
    tests above prove the wrapper keeps the exit-code contract on top of it."""

    def test_green_project_returns_pass_no_error_line(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        result = run_verify(_CLEAN_DOMAIN, str(tests_dir))
        assert isinstance(result, VerifyResult)
        assert result.exit_code == 0
        assert result.status == "pass"
        assert result.error_line == ""
        assert all(
            result.stages[s]["status"] == "pass" for s in ("init", "check", "tests")
        )

    def test_init_failure_returns_code_3_without_raising(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = run_verify(_INIT_FAIL_DOMAIN, str(empty))
        assert result.exit_code == 3
        assert result.status == "fail"
        assert result.stages["init"]["status"] == "fail"
        # An init failure carries its message as the red line the command prints.
        assert "Domain failed to initialize" in result.error_line
        # Check and tests never ran.
        assert result.stages["check"]["status"] == "skipped"
        assert result.stages["tests"]["status"] == "skipped"

    def test_check_failure_returns_code_4(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = run_verify(_WARN_DOMAIN, str(empty))
        assert result.exit_code == 4
        assert result.status == "fail"
        assert result.stages["check"]["status"] == "fail"
        assert result.stages["check"]["counts"]["warnings"] > 0
        # No early-exit error line on a stage failure that ran past init.
        assert result.error_line == ""

    def test_tests_failure_returns_code_5(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _FAILING_TEST)
        result = run_verify(_CLEAN_DOMAIN, str(tests_dir))
        assert result.exit_code == 5
        assert result.status == "fail"
        assert result.stages["tests"]["status"] == "fail"
        assert result.stages["tests"]["failed"] == 1
        # Check passed — codes are independent and precedence (check before
        # tests) is applied in the core.
        assert result.stages["check"]["status"] == "pass"

    def test_bad_path_is_a_usage_error_with_envelope_error(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        result = run_verify(_CLEAN_DOMAIN, str(missing))
        assert result.exit_code == 2
        # A usage error caught before any stage ran is envelope status "error",
        # and the message lands at ``data.error`` (envelope_error), not on a stage.
        assert result.status == "error"
        assert "--path is not a directory" in result.error_line
        assert result.envelope_error == result.error_line
        assert result.stages["init"]["status"] == "skipped"
