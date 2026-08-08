"""Tests for the ``protean verify`` CLI command.

``verify`` composes init + check + tests into one verdict with a stable exit
code contract:

    0 — all green            3 — check failed (bad [lint] config, or findings
    1 — usage error              at or above the [lint].level floor)
    2 — domain init failed   4 — tests failed

Exit 1 covers verify's own usage errors: domain not found, or a ``--path`` that
is not a directory.

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

    def test_human_table_shows_pytest_output_on_failure(self, tmp_path):
        """Without ``--json``, a failing test prints the tail of the pytest
        output under the stage table, so a human run is actionable and not just
        a FAIL label."""
        tests_dir = _write_test(tmp_path / "tests", _FAILING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir)],
        )
        assert result.exit_code == 4, result.output
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

    def test_domain_module_import_error_exits_2(self):
        """A domain module that fails to import with something other than
        ``ImportError`` (here, a plain ``RuntimeError``) is a load failure (2),
        not an unhandled traceback and not the domain-not-found usage error (1)."""
        result = runner.invoke(app, ["verify", "-d", _IMPORT_RAISES_DOMAIN])
        assert result.exit_code == 2, result.output
        assert "Domain failed to initialize" in result.stdout
        assert "Traceback" not in result.output

    def test_domain_module_import_error_json_envelope(self):
        result = runner.invoke(app, ["verify", "-d", _IMPORT_RAISES_DOMAIN, "--json"])
        assert result.exit_code == 2
        data = json.loads(result.stdout)
        assert data["verdict"] == "fail"
        assert data["stages"]["init"]["status"] == "fail"
        assert data["stages"]["check"]["status"] == "skipped"
        assert data["stages"]["tests"]["status"] == "skipped"

    def test_nested_import_error_exits_2_not_1(self):
        """A domain module found on disk, but whose own top-level ``import``
        fails, is a load failure (2) — even though ``locate_domain`` raises
        the same ``NoDomainException`` it uses for "module not found" (1)."""
        result = runner.invoke(app, ["verify", "-d", _NESTED_IMPORT_ERROR_DOMAIN])
        assert result.exit_code == 2, result.output
        assert "Error loading Protean domain" in result.stdout
        assert "While importing" in result.stdout

    def test_nested_import_error_json_envelope(self):
        result = runner.invoke(
            app, ["verify", "-d", _NESTED_IMPORT_ERROR_DOMAIN, "--json"]
        )
        assert result.exit_code == 2
        data = json.loads(result.stdout)
        assert data["verdict"] == "fail"
        assert data["stages"]["init"]["status"] == "fail"
        assert data["stages"]["check"]["status"] == "skipped"
        assert data["stages"]["tests"]["status"] == "skipped"

    def test_nested_import_error_table_row_is_single_line(self):
        """The multi-line ``While importing ...`` message (it embeds a full
        ``traceback.format_exc()``) is already printed in full above the
        table; the compact ``init`` row must collapse it to its first line
        instead of reproducing the traceback and breaking the table layout."""
        result = runner.invoke(app, ["verify", "-d", _NESTED_IMPORT_ERROR_DOMAIN])
        assert result.exit_code == 2, result.output
        table_lines = [
            line
            for line in result.stdout.splitlines()
            if line.strip().startswith("init")
        ]
        assert len(table_lines) == 1
        assert "Traceback" not in table_lines[0]


class TestVerifyLintConfig:
    """A malformed ``[lint]`` config must fail check (exit 3), not read as a
    false green. ``verify`` calls ``Domain.check()`` directly, whose IR build
    swallows the ``ConfigurationError`` a bad ``[lint]`` block raises, so verify
    runs the same config validation ``protean check`` does."""

    def test_bad_suppressions_count_exits_3(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _BAD_SUPPRESSIONS_DOMAIN, "--path", str(empty), "--json"],
        )
        assert result.exit_code == 3, result.output
        data = json.loads(result.stdout)
        assert data["verdict"] == "fail"
        assert data["stages"]["check"]["status"] == "fail"
        # The config error is surfaced as a check error (not swallowed).
        messages = " ".join(e["message"] for e in data["stages"]["check"]["errors"])
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
        assert result.exit_code == 3
        assert "[lint].suppressions" in result.stdout

    def test_non_table_lint_exits_3(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _BAD_LINT_TABLE_DOMAIN, "--path", str(empty), "--json"],
        )
        assert result.exit_code == 3, result.output
        data = json.loads(result.stdout)
        messages = " ".join(e["message"] for e in data["stages"]["check"]["errors"])
        assert "[lint]" in messages
        assert "must be a table" in messages

    def test_invalid_lint_level_exits_3(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = runner.invoke(
            app,
            ["verify", "-d", _BAD_LEVEL_DOMAIN, "--path", str(empty), "--json"],
        )
        assert result.exit_code == 3, result.output
        data = json.loads(result.stdout)
        messages = " ".join(e["message"] for e in data["stages"]["check"]["errors"])
        assert "[lint].level" in messages


class TestVerifyLintLevel:
    """The check stage honours ``[lint].level`` (default ``warn``), the same
    severity floor ``protean check`` uses — it does not hardcode the warn floor."""

    def test_level_error_opts_out_of_warning_gating(self, tmp_path):
        """A domain with warnings but ``[lint].level="error"`` passes check —
        only errors gate. With the warn floor hardcoded, this would exit 3."""
        tests_dir = _write_test(tmp_path / "tests", _PASSING_TEST)
        result = runner.invoke(
            app,
            ["verify", "-d", _LEVEL_ERROR_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["stages"]["check"]["status"] == "pass"
        # It really does carry warnings — the pass is because level="error", not
        # because the domain is clean.
        assert data["stages"]["check"]["counts"]["warnings"] > 0


class TestVerifyInternals:
    """Unit cover for the defensive helpers whose branches no end-to-end path
    reaches: an error-severity finding gates regardless of ``[lint].level``, and
    an unexpected ``Domain.check()`` crash is contracted to exit 3 rather than a
    traceback. The re-run inside ``check()`` has no known concrete trigger, so it
    can only be exercised directly."""

    def test_errors_gate_even_at_error_level(self):
        from protean.cli.verify import _check_gates

        assert _check_gates({"errors": 1, "warnings": 0, "infos": 0}, "error") is True

    def test_check_crash_is_surfaced_as_exit_3(self):
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


class TestVerifyUsageErrors:
    """``verify``'s own usage errors exit 1 with a clean message, no traceback."""

    def test_path_not_a_directory_exits_1(self, tmp_path):
        missing = tmp_path / "does" / "not" / "exist"
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(missing), "--json"],
        )
        assert result.exit_code == 1, result.output
        assert "Traceback" not in result.output
        data = json.loads(result.stdout)
        assert data["verdict"] == "fail"
        # Nothing ran — every stage is skipped.
        assert all(
            data["stages"][s]["status"] == "skipped" for s in ("init", "check", "tests")
        )

    def test_path_is_a_file_exits_1(self, tmp_path):
        a_file = tmp_path / "not_a_dir.txt"
        a_file.write_text("hi")
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(a_file)],
        )
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        # The clean usage message, which only the up-front guard emits — an
        # unguarded subprocess would raise NotADirectoryError instead.
        assert "--path is not a directory" in result.stdout

    def test_empty_domain_arg_exits_1(self, tmp_path, monkeypatch):
        """``-d ""`` with PROTEAN_DOMAIN unset is domain-not-found (exit 1),
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
        assert result.exit_code == 1
        assert "Traceback" not in result.output
        assert "No domain found" in result.stdout

    def test_bracketed_domain_name_survives_rich_markup(self):
        """A domain-not-found message that itself contains ``[...]`` (e.g. the
        module name echoed back in the error) must reach the user intact —
        both in the early ``[red]...[/red]`` line and the compact table row.
        Unescaped, ``rich`` treats ``[bogus]`` as a markup tag and strips it."""
        result = runner.invoke(app, ["verify", "-d", "[bogus]"])
        assert result.exit_code == 1
        assert "Could not import '[bogus]'" in result.stdout
        assert result.stdout.count("[bogus]") == 2  # early error line + table row


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
        # PROTEAN_ENV is special: the Protean pytest plugin re-establishes it via
        # ``setdefault`` at collection time. Popping it in verify lets the plugin's
        # own default ("test") win instead of the leaked parent value — so the
        # observable effect is "not the leaked value", not "absent". VIRTUAL_ENV
        # and PROTEAN_DEBUG are only ever read, so they stay absent.
        body = (
            "import os\n"
            "def test_env_scrubbed():\n"
            "    assert 'VIRTUAL_ENV' not in os.environ\n"
            "    assert 'PROTEAN_DEBUG' not in os.environ\n"
            "    assert os.environ.get('PROTEAN_ENV') != 'leaked'\n"
        )
        tests_dir = _write_test(tmp_path / "tests", body)
        result = runner.invoke(
            app,
            ["verify", "-d", _CLEAN_DOMAIN, "--path", str(tests_dir), "--json"],
        )
        # If verify did not scrub the vars, the child test asserts False → the
        # tests stage fails → exit 4.
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["stages"]["tests"]["status"] == "pass"
        assert data["stages"]["tests"]["passed"] == 1

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
        assert data["stages"]["tests"]["status"] == "pass"
        assert data["stages"]["tests"]["passed"] == 1


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
