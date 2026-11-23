"""Tests for ``protean add``: it applies a create-only aggregate slice by
default, previews it with ``--dry-run``, rolls back a failed apply, and the slice
it writes actually registers under traversal.

The traversal-load test is the sharp edge: a slice that is placed wrong, or whose
``__init__.py`` is not side-effect free, or whose imports do not resolve, makes
``init(traverse=True)`` crash or silently under-discover. Here we materialize the
planned files into a real generated project and assert the registry holds the new
elements after init.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.scaffold import CreateFileOperation
from protean.scaffold.add_plan import plan_add_slice
from tests.support.project_tests import passed_count, project_env, run_tests_in

# These generate and start their own projects; the autouse domain fixture would
# build an unrelated Domain per test for nothing.
pytestmark = pytest.mark.no_test_domain

_PACKAGE = "scaffolded"

# The files an `aggregate` slice writes, relative to the project root.
_SLICE_FILES = (
    "src/scaffolded/order/__init__.py",
    "src/scaffolded/order/aggregate_base.py",
    "src/scaffolded/order/aggregate.py",
    "src/scaffolded/order/commands.py",
    "src/scaffolded/order/events.py",
    "src/scaffolded/order/command_handlers.py",
    "src/scaffolded/order/projection.py",
    "src/scaffolded/order/projectors.py",
)


def _generate(tmp_path: Path, name: str = _PACKAGE) -> Path:
    """Run ``protean new`` and return the generated project root."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    result = CliRunner().invoke(
        app,
        ["new", name, "-o", str(out), "--defaults", "--skip-setup"],
    )
    assert result.exit_code == 0, f"protean new failed: {result.output}"
    return out / name


def _snapshot(root: Path) -> dict[str, bytes]:
    """Map every file under *root* to its bytes, for a before/after compare."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _materialize(project: Path, plan) -> None:
    """Write a plan's create operations into *project*, as apply would."""
    for op in plan.operations:
        assert isinstance(op, CreateFileOperation)
        target = project / op.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(op.content)


def test_dry_run_previews_the_create_operations(tmp_path):
    project = _generate(tmp_path)

    result = CliRunner().invoke(
        app, ["add", "aggregate", "Order", "--path", str(project), "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    for path in _SLICE_FILES:
        assert f"create {path}" in result.output, (
            f"preview did not name a create for {path}:\n{result.output}"
        )


def test_dry_run_writes_nothing(tmp_path):
    project = _generate(tmp_path)

    before = _snapshot(project)
    result = CliRunner().invoke(
        app, ["add", "aggregate", "Order", "--path", str(project), "--dry-run"]
    )
    after = _snapshot(project)

    assert result.exit_code == 0, result.output
    assert before == after, "a --dry-run add must not touch the project tree"


def test_default_applies_the_slice_and_a_rerun_conflicts(tmp_path):
    """Default (no flag) writes every file in the slice and exits 0. A second run
    hits the conflict pre-flight, exits non-zero, and leaves the files it wrote
    intact."""
    project = _generate(tmp_path)

    result = CliRunner().invoke(
        app, ["add", "aggregate", "Order", "--path", str(project)]
    )

    assert result.exit_code == 0, result.output
    for path in _SLICE_FILES:
        assert (project / path).is_file(), f"add did not write {path}:\n{result.output}"
        assert path in result.output, (
            f"the confirmation did not name {path}:\n{result.output}"
        )

    # A re-run is a conflict: create-only apply refuses to clobber, exits 1, and
    # the already-written files stay exactly as they were.
    after_first = _snapshot(project)
    rerun = CliRunner().invoke(
        app, ["add", "aggregate", "Order", "--path", str(project)]
    )

    assert rerun.exit_code == 1, rerun.output
    assert _snapshot(project) == after_first, "a conflicting re-run must change nothing"


def test_apply_flag_applies_the_slice(tmp_path):
    """The explicit ``--apply`` flag writes the same slice files as the default."""
    project = _generate(tmp_path)

    result = CliRunner().invoke(
        app, ["add", "aggregate", "Order", "--path", str(project), "--apply"]
    )

    assert result.exit_code == 0, result.output
    for path in _SLICE_FILES:
        assert (project / path).is_file(), f"--apply did not write {path}"


def test_dry_run_and_apply_together_is_a_usage_error(tmp_path):
    """The two flags contradict each other, so the command rejects the pair with
    the usage exit code and writes nothing."""
    project = _generate(tmp_path)

    before = _snapshot(project)
    result = CliRunner().invoke(
        app,
        ["add", "aggregate", "Order", "--path", str(project), "--dry-run", "--apply"],
    )
    after = _snapshot(project)

    assert result.exit_code == 2, result.output
    assert "cannot be used together" in result.output, (
        f"the error should explain the flags conflict:\n{result.output}"
    )
    assert before == after, "a rejected flag combination must not touch the tree"


def test_mid_apply_failure_leaves_the_tree_unchanged(tmp_path):
    """Acceptance #3 through the CLI: put a plain file where the slice *directory*
    must go. The pre-flight cannot see the slice files as conflicts (their parent
    is a file, so they do not exist), so apply starts writing and fails on the
    first file. That trips the rollback path, and the command must exit 1 with the
    tree unchanged: only the pre-seeded file remains."""
    project = _generate(tmp_path)

    # A regular file named `order` sits exactly where `src/scaffolded/order/` must
    # be created, so mkdir/write under it raises NotADirectoryError mid-apply.
    clash = project / "src/scaffolded/order"
    clash.write_text("not a directory\n")

    before = _snapshot(project)
    result = CliRunner().invoke(
        app, ["add", "aggregate", "Order", "--path", str(project)]
    )
    after = _snapshot(project)

    assert result.exit_code == 1, result.output
    assert before == after, "a failed apply must roll the tree back unchanged"
    # Nothing from the aborted apply survived; the pre-seeded file is intact.
    assert clash.read_text() == "not a directory\n"


def test_apply_then_verify_is_green(tmp_path):
    """Acceptance #2: apply the slice, then ``protean verify`` in the project must
    pass. Runs verify as a real subprocess (init + check + the project's pytest
    suite), the same harness the verify end-to-end test uses, so a slice that is
    placed wrong or does not check clean fails here."""
    project = _generate(tmp_path)

    result = CliRunner().invoke(
        app, ["add", "aggregate", "Order", "--path", str(project)]
    )
    assert result.exit_code == 0, result.output
    # Prove the apply actually wrote the slice, so a verify-green verdict reflects
    # the applied slice rather than the base project (which is green on its own).
    for path in _SLICE_FILES:
        assert (project / path).is_file(), f"apply did not write {path}"

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
        ],
        cwd=project,
        env=project_env(project),
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )

    assert completed.returncode == 0, (
        "protean verify must pass after applying the slice:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )


def test_planned_slices_load_and_register_under_traversal(tmp_path):
    """Acceptance #3: the planned files register when the domain inits with
    traversal on, and the slices actually work. Materialize the plans for a
    single-word and a multi-word aggregate, then run `project_checks/
    test_added_slices.py` in the project: it requires every element of each slice
    in the registry by name, and processes each create command through the
    generated handler.

    Asserting only the registry names is not enough: a broken `create` factory or
    a handler missing its decorator can still leave the names present. Running the
    command exercises the factory and the handler body, so those regressions fail
    here. The multi-word slice lands in `order_item/`, so traversal has to
    discover it there under the derived class names."""
    project = _generate(tmp_path)
    for name in ("Order", "order_item"):
        _materialize(project, plan_add_slice(str(project), "aggregate", name))

    result = run_tests_in(
        project,
        [Path(__file__).parent / "project_checks" / "test_added_slices.py"],
        "tests/scaffolded/application",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert passed_count(result) == 4, result.stdout


def test_unsupported_type_exits_nonzero_and_writes_nothing(tmp_path):
    project = _generate(tmp_path)

    before = _snapshot(project)
    result = CliRunner().invoke(app, ["add", "widget", "Foo", "--path", str(project)])
    after = _snapshot(project)

    # 2 is the documented usage exit code; pin it, not just "non-zero".
    assert result.exit_code == 2, result.output
    assert "aggregate" in result.output, (
        f"the error should name aggregate as the supported type:\n{result.output}"
    )
    assert before == after, "a rejected add must not touch the project tree"


def test_keyword_name_exits_two_and_writes_nothing(tmp_path):
    """A Python keyword would produce a slice that does not compile, so the
    command must reject it with the usage exit code and write nothing."""
    project = _generate(tmp_path)

    before = _snapshot(project)
    result = CliRunner().invoke(
        app, ["add", "aggregate", "class", "--path", str(project)]
    )
    after = _snapshot(project)

    assert result.exit_code == 2, result.output
    assert "keyword" in result.output, (
        f"the error should explain the name is a Python keyword:\n{result.output}"
    )
    assert before == after, "a rejected add must not touch the project tree"
