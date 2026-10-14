"""The claims on ``docs/reference/testing/pytest-plugin.md`` hold under pytest.

The option and marker checks run in an empty directory with no ini file, so
everything they find comes from the auto-registered plugin, not from the
repository's ``pyproject.toml``.
"""

import pytest

from tests.docs.support import outcome_counts, run_example_tests

pytestmark = pytest.mark.no_test_domain


def test_the_opt_in_examples_pass():
    result = run_example_tests(
        "reference/testing/pytest-plugin/opt_in/test_opt_in.py",
        args=["-W", "error::pytest.PytestUnknownMarkWarning"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 4}


@pytest.fixture
def bare_root(tmp_path):
    (tmp_path / "test_nothing.py").write_text("")
    return tmp_path


def test_the_plugin_adds_the_documented_options(bare_root):
    result = run_example_tests("test_nothing.py", args=["--help"], root=bare_root)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "--protean-env=" in result.stdout
    assert "--update-snapshots" in result.stdout


def test_the_plugin_registers_the_documented_markers(bare_root):
    result = run_example_tests("test_nothing.py", args=["--markers"], root=bare_root)

    registered = {
        line.split(":", 1)[0].removeprefix("@pytest.mark.")
        for line in result.stdout.splitlines()
        if line.startswith("@pytest.mark.")
    }
    assert result.returncode == 0, result.stdout + result.stderr
    assert {"domain", "application", "integration", "slow", "bdd"} <= registered
    assert "no_test_domain" not in registered  # only the conformance opt-in adds it


@pytest.mark.parametrize(
    "args, env, expected",
    [
        pytest.param([], {}, "test", id="default"),
        pytest.param(["--protean-env=staging"], {}, "staging", id="option"),
        pytest.param(
            ["--protean-env=staging"],
            {"PROTEAN_ENV": "production"},
            "production",
            id="already-set",
        ),
    ],
)
def test_the_protean_env_option_sets_protean_env(tmp_path, args, env, expected):
    (tmp_path / "test_env.py").write_text(
        "import os\n\n\n"
        "def test_env():\n"
        f"    assert os.environ['PROTEAN_ENV'] == {expected!r}\n"
    )

    result = run_example_tests("test_env.py", args=args, env=env, root=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 1}
