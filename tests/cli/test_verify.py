"""Tests for the ``protean verify`` CLI command.

``verify`` composes init + check + tests into one verdict with a stable exit
code contract:

    0 — all green            3 — check failed (errors or warnings)
    1 — domain not found     4 — tests failed
    2 — domain init failed

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

import pytest
from typer.testing import CliRunner

from protean.cli import app

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
        assert data["verdict"] == "pass"
        # No stage may report a failure on the green path (guards a vacuous pass).
        assert all(
            data["stages"][s]["status"] == "pass" for s in ("init", "check", "tests")
        )

    def test_json_envelope_has_settled_keys(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        data = json.loads(result.stdout)
        # Top-level envelope is exactly {verdict, stages}.
        assert set(data.keys()) == {"verdict", "stages"}
        assert set(data["stages"].keys()) == {"init", "check", "tests"}
        # Each stage carries its settled sub-keys.
        assert "status" in data["stages"]["init"]
        assert {"status", "counts", "diagnostics"} <= set(data["stages"]["check"])
        assert {"status", "returncode", "passed", "failed"} <= set(
            data["stages"]["tests"]
        )
        assert data["stages"]["tests"]["passed"] == 1
        assert data["stages"]["tests"]["returncode"] == 0

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
    """A domain with check warnings exits 3, independent of the tests stage."""

    def test_check_warnings_exit_3(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _WARN_DOMAIN, "--path", str(empty), "--json"],
        )
        assert result.exit_code == 3, result.output
        data = json.loads(result.stdout)
        assert data["verdict"] == "fail"
        assert data["stages"]["check"]["status"] == "fail"
        assert data["stages"]["check"]["counts"]["warnings"] > 0
        # The failing diagnostics are carried in the envelope.
        codes = {d["code"] for d in data["stages"]["check"]["diagnostics"]}
        assert "UNHANDLED_EVENT" in codes

    def test_check_failure_named_in_rich_output(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _WARN_DOMAIN, "--path", str(empty)],
        )
        assert result.exit_code == 3
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
        assert data["stages"]["check"]["status"] == "pass"
        # It really is info-only (proves the pass is not because it is clean).
        assert data["stages"]["check"]["counts"]["infos"] > 0
        assert data["stages"]["check"]["counts"]["warnings"] == 0


class TestVerifyTestFailure:
    """A clean domain with a failing test exits 4; check stays independent."""

    def test_failing_test_exits_4(self, tmp_path):
        tests_dir = _write_test(tmp_path / "tests", _FAILING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        assert result.exit_code == 4, result.output
        data = json.loads(result.stdout)
        assert data["verdict"] == "fail"
        assert data["stages"]["tests"]["status"] == "fail"
        assert data["stages"]["tests"]["returncode"] != 0
        assert data["stages"]["tests"]["failed"] == 1
        # Check passed — the codes are independent and precedence is right.
        assert data["stages"]["check"]["status"] == "pass"

    def test_check_failure_takes_precedence_over_test_failure(self, tmp_path):
        """When check AND tests both fail, the exit code is check's (3), not 4."""
        tests_dir = _write_test(tmp_path / "tests", _FAILING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _WARN_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        assert result.exit_code == 3, result.output
        data = json.loads(result.stdout)
        # Both stages record their failure even though check's code wins.
        assert data["stages"]["check"]["status"] == "fail"
        assert data["stages"]["tests"]["status"] == "fail"


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
        assert data["stages"]["tests"]["status"] == "pass"
        # The returncode is preserved so "no tests" is distinguishable.
        assert data["stages"]["tests"]["returncode"] == 5
        assert data["stages"]["tests"]["passed"] == 0


class TestVerifyLoadFailures:
    """Domain-not-found (1) and domain-init-failed (2) are distinct codes."""

    def test_domain_not_found_exits_1(self):
        result = runner.invoke(app, ["verify", "-d", "nonexistent.module"])
        assert result.exit_code == 1
        assert "Error loading Protean domain" in result.stdout
        # A clean message, not a traceback.
        assert "Traceback" not in result.output

    def test_domain_not_found_json_envelope(self):
        result = runner.invoke(app, ["verify", "-d", "nonexistent.module", "--json"])
        assert result.exit_code == 1
        data = json.loads(result.stdout)
        assert data["verdict"] == "fail"
        assert data["stages"]["init"]["status"] == "fail"
        # Check and tests never ran.
        assert data["stages"]["check"]["status"] == "skipped"
        assert data["stages"]["tests"]["status"] == "skipped"

    def test_init_failure_exits_2(self):
        result = runner.invoke(app, ["verify", "-d", _INIT_FAIL_DOMAIN])
        assert result.exit_code == 2
        assert "Domain failed to initialize" in result.stdout
        assert "Traceback" not in result.output

    def test_init_failure_is_distinct_from_not_found(self):
        """A found-but-broken domain is 2; a missing one is 1."""
        found_broken = runner.invoke(app, ["verify", "-d", _INIT_FAIL_DOMAIN])
        missing = runner.invoke(app, ["verify", "-d", "nonexistent.module"])
        assert found_broken.exit_code == 2
        assert missing.exit_code == 1
        assert found_broken.exit_code != missing.exit_code


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
        )

        assert completed.returncode == 0, (
            "`protean verify` must pass on a freshly generated project:\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
        data = json.loads(completed.stdout)
        assert data["verdict"] == "pass"
        assert data["stages"]["init"]["status"] == "pass"
        assert data["stages"]["check"]["status"] == "pass"
        assert data["stages"]["tests"]["status"] == "pass"
        # The scaffold ships passing tests; verify actually ran them.
        assert data["stages"]["tests"]["passed"] >= 1
