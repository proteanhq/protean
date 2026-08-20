"""Tests for ``protean add``: it applies a create-only aggregate slice by
default, previews it with ``--dry-run``, rolls back a failed apply, and the slice
it writes actually registers under traversal.

The traversal-load test is the sharp edge (issue acceptance #3): a slice that is
placed wrong, or whose ``__init__.py`` is not side-effect free, or whose imports
do not resolve, makes ``init(traverse=True)`` crash or silently under-discover.
Here we materialize the planned files into a real generated project and assert the
registry holds the new elements after init.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from protean.cli import app
from protean.scaffold import CreateFileOperation
from protean.scaffold.add_plan import plan_add_slice

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


def _subprocess_env(project: Path) -> dict[str, str]:
    """Env for running the generated project uninstalled (its ``src/`` on the
    path, and the leak-prone vars dropped). Mirrors the working-project test."""
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


def _init_and_exercise(class_name: str, slug: str) -> str:
    """The script the traversal test runs inside the generated project: init the
    domain, print the registry, then drive the planned slice end to end.

    Takes the slice's class name and slug so a multi-word aggregate is exercised
    through its own module path (``order_item/``) and class (``OrderItem``)."""
    return (
        "import sys; sys.path.insert(0, 'src')\n"
        "from scaffolded.domain import scaffolded as domain\n"
        "domain.init()\n"
        "names = sorted(domain.registry._elements_by_name.keys())\n"
        "print('NAMES:' + ','.join(names))\n"
        # Drive the slice end to end: process the command through the generated
        # handler (which calls the generated `create` factory), then fetch the
        # persisted aggregate back. command_processing is sync in the scaffold, so
        # process runs the handler inline and returns the aggregate id.
        f"from scaffolded.{slug}.commands import Create{class_name}\n"
        f"from scaffolded.{slug}.aggregate import {class_name}\n"
        "with domain.domain_context():\n"
        f"    new_id = domain.process(Create{class_name}(name='Widget'))\n"
        f"    fetched = domain.repository_for({class_name}).get(new_id)\n"
        "    print('PERSISTED:' + fetched.name)\n"
    )


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
        env=_subprocess_env(project),
        capture_output=True,
        text=True,
        errors="replace",
    )

    assert completed.returncode == 0, (
        "protean verify must pass after applying the slice:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )


@pytest.mark.parametrize(
    ("name", "class_name", "slug"),
    [
        ("Order", "Order", "order"),
        # A multi-word name: the slice lands in `order_item/` and the traversal
        # has to discover it there under the derived class names.
        ("order_item", "OrderItem", "order_item"),
    ],
)
def test_planned_slice_loads_and_registers_under_traversal(
    tmp_path, name, class_name, slug
):
    """Acceptance #3: the planned files register when the domain inits with
    traversal on, and the slice actually works. Materialize the plan, init the
    real domain, require all four elements in the registry by name, then process a
    command through the generated handler and assert the aggregate persists.

    Asserting only the registry names is not enough: a broken `create` factory or
    a handler missing its decorator can still leave the names present. Running the
    command exercises the factory and the handler body, so those regressions fail
    here."""
    project = _generate(tmp_path)
    plan = plan_add_slice(str(project), "aggregate", name)
    _materialize(project, plan)

    completed = subprocess.run(
        [sys.executable, "-c", _init_and_exercise(class_name, slug)],
        cwd=project,
        env=_subprocess_env(project),
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, (
        "the domain must init and process the planned slice's command:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )
    line = next(
        (ln for ln in completed.stdout.splitlines() if ln.startswith("NAMES:")),
        "",
    )
    registered = set(line[len("NAMES:") :].split(","))
    for element in (
        class_name,
        f"Create{class_name}",
        f"{class_name}Created",
        f"{class_name}CommandHandler",
        f"{class_name}Summary",
        f"{class_name}Projector",
    ):
        assert element in registered, (
            f"{element} did not register under traversal; registered: "
            f"{sorted(registered)}"
        )
    # The command ran through the generated handler and the aggregate came back.
    assert "PERSISTED:Widget" in completed.stdout, (
        "the generated handler did not create and persist the aggregate:\n"
        f"{completed.stdout}\n{completed.stderr}"
    )


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
