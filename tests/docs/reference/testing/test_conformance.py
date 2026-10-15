"""The claims on ``docs/reference/testing/conformance.md`` hold under pytest."""

import re

import pytest

from tests.docs.support import outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain

CONFORMANCE_PLUGIN = "protean.integrations.pytest.adapter_conformance"


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
