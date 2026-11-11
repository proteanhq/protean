"""The claims on ``docs/reference/testing/conformance.md`` hold under pytest."""

import re
import shutil
from pathlib import Path

import pytest

from tests.docs.support import (
    DOCS_SRC,
    REPO_ROOT,
    outcome_counts,
    run_example_tests,
)

pytestmark = pytest.mark.no_test_domain

CONFORMANCE_PLUGIN = "protean.integrations.pytest.adapter_conformance"
PORT_PLUGIN = REPO_ROOT / "tests/conformance/conftest.py"
# The child imports the plugin as ``tests.conformance.conftest`` from the repo.
REPO_ON_PATH = {"PYTHONPATH": str(REPO_ROOT)}
PORT_SUITE_EXAMPLE = (
    DOCS_SRC / "reference/testing/conformance/port_suite/test_capability_gates.py"
)


def test_the_opt_in_runs_tests_against_the_memory_adapter():
    result = run_example_tests(
        "reference/testing/conformance/opt_in/test_default_adapter.py"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 1}


def test_the_opt_in_provides_the_documented_fixtures():
    result = run_example_tests(
        "reference/testing/conformance/opt_in/test_default_adapter.py",
        args=["--fixtures"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert fixture_scopes(result.stdout) == {
        "db_config": "session",
        "store_config": "session",
        "broker_config": "session",
        "test_domain": "function",
        "db": "function",
        "run_around_tests": "function",
    }


def fixture_scopes(listing):
    """Map each fixture in a ``--fixtures`` listing that the page names to its scope.

    pytest prints ``name [session scope] -- file:line``; a function-scoped
    fixture has no bracket.
    """
    documented = {
        "db_config",
        "store_config",
        "broker_config",
        "test_domain",
        "db",
        "run_around_tests",
    }
    scopes = {}
    for line in listing.splitlines():
        match = re.match(r"(\w+)(?: \[(\w+) scope\])? -- ", line)
        if match and match[1] in documented:
            scopes[match[1]] = match[2] or "function"
    return scopes


def test_the_plugin_adds_the_documented_options(tmp_path):
    (tmp_path / "test_nothing.py").write_text("")

    result = run_example_tests(
        "test_nothing.py", args=["-p", CONFORMANCE_PLUGIN, "--help"], root=tmp_path
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for option in ("--db=", "--db-provider=", "--db-uri=", "--db-extra="):
        assert option in result.stdout


def test_the_custom_field_conformance_example_passes():
    result = run_example_tests("reference/testing/conformance/002.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 1}


class TestThePortSuitePlugin:
    """The page's ``tests/conformance/`` example runs under the plugin."""

    def test_the_example_runs_against_the_memory_adapter(self):
        result = run_example_tests(
            "reference/testing/conformance/port_suite/test_capability_gates.py",
            args=[
                "-rs",
                "-p",
                "tests.conformance.conftest",
                "--port",
                "database",
                "--adapter",
                "memory",
            ],
            env=REPO_ON_PATH,
        )

        assert result.returncode == 0, result.stdout + result.stderr
        assert outcome_counts(result) == {"passed": 3, "skipped": 1}
        assert "memory does not declare NATIVE_JSON" in result.stdout

    @pytest.fixture
    def suite(self, tmp_path: Path) -> Path:
        """Copy the example into ``conformance/database/`` beside the plugin.

        The plugin reads the port from that folder, and ``--capability``
        filters only tests inside it.
        """
        (tmp_path / "conformance" / "database").mkdir(parents=True)
        shutil.copy(PORT_PLUGIN, tmp_path / "conformance" / "conftest.py")
        shutil.copy(
            PORT_SUITE_EXAMPLE,
            tmp_path / "conformance" / "database" / "test_capability_gates.py",
        )
        return tmp_path

    def run_suite(self, suite: Path, *args: str):
        return run_example_tests(
            "conformance/database/test_capability_gates.py",
            args=["--rootdir", str(suite), *args],
            root=suite,
            env=REPO_ON_PATH,
        )

    def test_capability_keeps_only_the_tests_that_name_the_flag(self, suite):
        result = self.run_suite(suite, "--capability", "CRUD")

        assert result.returncode == 0, result.stdout + result.stderr
        assert outcome_counts(result) == {"passed": 1}
        assert "3 deselected" in result.stdout

    def test_capability_none_keeps_only_the_ungated_test(self, suite):
        result = self.run_suite(suite, "--capability", "none", "-v")

        assert result.returncode == 0, result.stdout + result.stderr
        assert outcome_counts(result) == {"passed": 1}
        assert "test_every_adapter_reports_its_capabilities PASSED" in result.stdout

    def test_adapter_config_must_be_a_json_object(self, suite):
        result = self.run_suite(suite, "--adapter-config", "[1]")

        assert result.returncode == 4
        assert "--adapter-config must be a JSON object, got list" in (
            result.stdout + result.stderr
        )

    def test_the_plugin_adds_the_documented_options(self, suite):
        result = self.run_suite(suite, "--help")

        assert result.returncode == 0, result.stdout + result.stderr
        for option in ("--port=", "--adapter=", "--adapter-config=", "--capability="):
            assert option in result.stdout
