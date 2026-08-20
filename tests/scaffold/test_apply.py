"""Tests for the ChangePlan applier: ``apply_plan`` writes a create-only plan
atomically, or leaves the tree byte-for-byte unchanged.

These are pure filesystem tests against ``tmp_path``; no domain fixture and no
mocks. The sharp edges are the atomic-rollback branch (issue acceptance #3) and
the rule that rollback removes exactly the paths this call created and nothing
that was already on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean.scaffold import (
    ApplyError,
    ChangePlan,
    ConfigOperation,
    CreateFileOperation,
    EditFileOperation,
    apply_plan,
)

# Pure filesystem tests; the autouse domain fixture would build an unrelated
# Domain per test for nothing.
pytestmark = pytest.mark.no_test_domain


def _snapshot(root: Path) -> dict[str, bytes]:
    """Map every file under *root* to its bytes, for a before/after compare."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_apply_writes_every_create_operation(tmp_path):
    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/order/__init__.py", content="pkg init\n"),
            CreateFileOperation(
                path="src/pkg/order/aggregate.py", content="class Order:\n    pass\n"
            ),
            CreateFileOperation(path="top.txt", content="at the root\n"),
        ),
    )

    written = apply_plan(str(tmp_path), plan)

    assert written == (
        "src/pkg/order/__init__.py",
        "src/pkg/order/aggregate.py",
        "top.txt",
    )
    # Contents match byte-for-byte, and parent directories were created.
    assert (tmp_path / "src/pkg/order/__init__.py").read_text() == "pkg init\n"
    assert (
        tmp_path / "src/pkg/order/aggregate.py"
    ).read_text() == "class Order:\n    pass\n"
    assert (tmp_path / "top.txt").read_text() == "at the root\n"
    assert (tmp_path / "src/pkg/order").is_dir()


def test_empty_plan_writes_nothing_and_returns_empty(tmp_path):
    before = _snapshot(tmp_path)

    written = apply_plan(str(tmp_path), ChangePlan())

    assert written == ()
    assert _snapshot(tmp_path) == before


def test_conflict_preflight_refuses_and_writes_nothing(tmp_path):
    """A plan whose second target already exists is refused before any write, so
    the first op's file is never created."""
    existing = tmp_path / "src/pkg/events.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("hand written\n")

    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/aggregate.py", content="new file\n"),
            CreateFileOperation(path="src/pkg/events.py", content="would clobber\n"),
        ),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "events.py" in str(excinfo.value)
    # The pre-existing file is untouched and the first op never landed.
    assert existing.read_text() == "hand written\n"
    assert not (tmp_path / "src/pkg/aggregate.py").exists()
    assert _snapshot(tmp_path) == before


def test_edit_operation_is_rejected_and_writes_nothing(tmp_path):
    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/aggregate.py", content="new file\n"),
            EditFileOperation(path="src/pkg/existing.py", diff="@@ -1 +1 @@\n-a\n+b\n"),
        ),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "create operations only" in str(excinfo.value)
    # Rejected up front: even the create that came first is not written.
    assert not (tmp_path / "src/pkg/aggregate.py").exists()
    assert _snapshot(tmp_path) == before


def test_config_operation_is_rejected_and_writes_nothing(tmp_path):
    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/aggregate.py", content="new file\n"),
            ConfigOperation(key_path=("databases", "default"), value={"provider": "x"}),
        ),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError):
        apply_plan(str(tmp_path), plan)

    assert not (tmp_path / "src/pkg/aggregate.py").exists()
    assert _snapshot(tmp_path) == before


def test_mid_apply_failure_rolls_the_tree_back(tmp_path):
    """The atomic-rollback branch (acceptance #3), mock-free. Op 1 creates a
    file; op 2's parent path *is* that file, so writing op 2 fails. The whole
    apply must roll back: op 1's file gone, the directory this call created gone,
    the pre-existing root intact."""
    (tmp_path / "keep.txt").write_text("pre-existing\n")

    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="pkg/thing.py", content="op one\n"),
            # Writing under `pkg/thing.py/` fails: thing.py is a file, not a dir.
            CreateFileOperation(path="pkg/thing.py/nested.py", content="op two\n"),
        ),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "rolled back" in str(excinfo.value)
    # Op 1's file is gone, the `pkg/` directory this call made is gone, and the
    # pre-existing file survives: the tree is exactly what it was.
    assert not (tmp_path / "pkg/thing.py").exists()
    assert not (tmp_path / "pkg").exists()
    assert (tmp_path / "keep.txt").read_text() == "pre-existing\n"
    assert _snapshot(tmp_path) == before


def test_rollback_leaves_a_preexisting_directory_intact(tmp_path):
    """Rollback removes only the directories this call created. A slice directory
    that already exists on disk must survive a failed apply."""
    package_dir = tmp_path / "src" / "pkg"
    package_dir.mkdir(parents=True)
    (package_dir / "domain.py").write_text("existing module\n")

    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/thing.py", content="op one\n"),
            CreateFileOperation(path="src/pkg/thing.py/nested.py", content="op two\n"),
        ),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError):
        apply_plan(str(tmp_path), plan)

    # The op-1 file is rolled back, but the pre-existing src/pkg/ and its module
    # are untouched: this call did not create that directory, so it must not
    # remove it.
    assert not (package_dir / "thing.py").exists()
    assert package_dir.is_dir()
    assert (package_dir / "domain.py").read_text() == "existing module\n"
    assert _snapshot(tmp_path) == before
