"""Tests for the helpers the docs_src tests load and run examples with."""

import subprocess
import sys

import pytest

from protean import Domain
from tests.docs.support import (
    REPO_ROOT,
    load_example,
    module_name_for,
    outcome_counts,
    run_example_tests,
)

pytestmark = pytest.mark.no_test_domain


def test_module_name_is_built_from_the_path():
    assert (
        module_name_for("guides/getting-started/es-tutorial/ch08.py")
        == "docs_src_guides_getting_started_es_tutorial_ch08"
    )


def test_loads_an_example_and_registers_it():
    module = load_example("guides/getting-started/hello.py")

    assert module.__name__ == "docs_src_guides_getting_started_hello"
    assert sys.modules[module.__name__] is module
    assert isinstance(module.domain, Domain)
    with module.domain.domain_context():
        task = module.Task(title="Buy groceries")
        repo = module.domain.repository_for(module.Task)
        repo.add(task)
        assert repo.get(task.id).title == "Buy groceries"
        assert repo.get(task.id).done is False


def test_a_missing_example_raises():
    with pytest.raises(FileNotFoundError, match="no docs_src example at nope.py"):
        load_example("nope.py")


def test_a_failing_example_is_not_left_in_sys_modules(tmp_path):
    (tmp_path / "broken.py").write_text("raise RuntimeError('boom')\n")

    with pytest.raises(RuntimeError, match="boom"):
        load_example("broken.py", root=tmp_path)

    assert module_name_for("broken.py") not in sys.modules


# --- run_example_tests and outcome_counts --------------------------------------


def _example(tmp_path, source):
    (tmp_path / "test_example.py").write_text(source)
    return "test_example.py"


def test_a_passing_example_exits_zero_and_reports_its_count(tmp_path):
    path = _example(tmp_path, "def test_one():\n    assert 1 + 1 == 2\n")

    result = run_example_tests(path, root=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 1}


def test_a_failing_example_names_the_failing_test(tmp_path):
    path = _example(
        tmp_path,
        "def test_good():\n    pass\n\n\ndef test_bad():\n    assert 1 == 2\n",
    )

    result = run_example_tests(path, root=tmp_path)

    assert result.returncode == 1
    assert " test_bad " in result.stdout
    assert " test_good " not in result.stdout
    assert outcome_counts(result) == {"failed": 1, "passed": 1}


def test_an_example_without_tests_exits_five(tmp_path):
    path = _example(tmp_path, "x = 1\n")

    result = run_example_tests(path, root=tmp_path)

    assert result.returncode == 5


def test_env_reaches_the_child(tmp_path):
    path = _example(
        tmp_path,
        "import os\n\n\ndef test_env():\n"
        "    assert os.environ['DOCS_EXAMPLE_FLAG'] == 'on'\n",
    )

    result = run_example_tests(path, root=tmp_path, env={"DOCS_EXAMPLE_FLAG": "on"})

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_example_root_is_importable_in_the_child(tmp_path):
    (tmp_path / "helper.py").write_text("VALUE = 42\n")
    path = _example(
        tmp_path,
        "from helper import VALUE\n\n\ndef test_v():\n    assert VALUE == 42\n",
    )

    result = run_example_tests(path, root=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_package_parent_is_importable_in_the_child(tmp_path):
    package = tmp_path / "guides" / "shared" / "shop"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("NAME = 'shop'\n")
    path = _example(
        tmp_path,
        "from shop import NAME\n\n\ndef test_name():\n    assert NAME == 'shop'\n",
    )

    result = run_example_tests(path, root=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr


def test_the_repo_pytest_config_does_not_apply(tmp_path):
    # The repo config turns on --doctest-modules, which would collect and fail
    # this docstring. The empty config leaves only the one test.
    path = _example(
        tmp_path,
        '"""\n>>> 1 + 1\n3\n"""\n\n\ndef test_one():\n    pass\n',
    )

    result = run_example_tests(path, root=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 1}


def test_files_the_example_writes_land_outside_the_repo(tmp_path):
    path = _example(
        tmp_path,
        "from pathlib import Path\n\n\ndef test_write():\n"
        "    Path('docs_example_output.txt').write_text('x')\n"
        "    print(Path.cwd())\n",
    )

    result = run_example_tests(path, root=tmp_path, args=["-s"])

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (REPO_ROOT / "docs_example_output.txt").exists()
    assert not (tmp_path / "docs_example_output.txt").exists()
    assert not (tmp_path / "__pycache__").exists()
    assert not (tmp_path / ".pytest_cache").exists()


def test_a_missing_example_to_run_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="no docs_src example at nope.py"):
        run_example_tests("nope.py", root=tmp_path)


def _done(stdout):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout)


def test_outcome_counts_reads_the_last_summary_line():
    stdout = (
        "collected 6 items\n\n"
        "=== 3 passed, 1 failed, 1 skipped, 2 errors in 0.12s ===\n\n"
    )

    assert outcome_counts(_done(stdout)) == {
        "passed": 3,
        "failed": 1,
        "skipped": 1,
        "errors": 2,
    }


def test_outcome_counts_folds_a_single_error_into_errors():
    assert outcome_counts(_done("=== 1 error in 0.01s ===\n")) == {"errors": 1}


def test_outcome_counts_of_no_output_is_empty():
    assert outcome_counts(_done("")) == {}
