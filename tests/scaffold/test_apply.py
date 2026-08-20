"""Tests for the ChangePlan applier: ``apply_plan`` writes a create-only plan
atomically, or leaves the tree byte-for-byte unchanged.

These are pure filesystem tests against ``tmp_path``; no domain fixture and no
mocks. The sharp edges are the atomic-rollback branch (issue acceptance #3) and
the rule that rollback removes exactly the paths this call created and nothing
that was already on disk.
"""

from __future__ import annotations

import os
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


def test_conflict_preflight_refuses_a_broken_symlink_target(tmp_path):
    """A dangling symlink at a target counts as a conflict. ``Path.exists()``
    follows the link and reads ``False`` for a broken one, so without the
    symlink-aware check the pre-flight would treat the path as free and write
    through the link, past the create-only guarantee."""
    link = tmp_path / "src/pkg/aggregate.py"
    link.parent.mkdir(parents=True)
    link.symlink_to(tmp_path / "does-not-exist")
    assert link.is_symlink() and not link.exists()

    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/aggregate.py", content="new file\n"),
        ),
    )

    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "aggregate.py" in str(excinfo.value)
    # The link is left exactly as found: still a dangling symlink, not a file.
    assert link.is_symlink() and not link.exists()


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
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "create operations only" in str(excinfo.value)
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


def test_rollback_undoes_many_files_and_deep_dirs_on_a_non_last_failure(tmp_path):
    """Exercise the deletion machinery, not just its zero/one case: two files
    already written across three new directory levels, and the op that fails is
    not the last op in the plan. Rollback must unlink both files, remove all
    three directories it created (deepest-first), leave the pre-existing root
    file alone, and never reach the op after the failing one."""
    (tmp_path / "keep.txt").write_text("pre-existing\n")

    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/order/__init__.py", content="one\n"),
            CreateFileOperation(path="src/pkg/order/aggregate.py", content="two\n"),
            # aggregate.py is a file, so writing under it fails. This is op 3 of 4:
            # the failure is not the last op.
            CreateFileOperation(
                path="src/pkg/order/aggregate.py/nested.py", content="three\n"
            ),
            CreateFileOperation(path="src/pkg/other.py", content="never reached\n"),
        ),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError):
        apply_plan(str(tmp_path), plan)

    # Both already-written files are unlinked and all three created directories
    # are removed, so the whole src/ tree this call built is gone.
    assert not (tmp_path / "src/pkg/order/__init__.py").exists()
    assert not (tmp_path / "src/pkg/order/aggregate.py").exists()
    assert not (tmp_path / "src").exists()
    # The op after the failing one never ran.
    assert not (tmp_path / "src/pkg/other.py").exists()
    # The pre-existing root file survives, and the tree is exactly as it was.
    assert (tmp_path / "keep.txt").read_text() == "pre-existing\n"
    assert _snapshot(tmp_path) == before


def test_rollback_unlinks_a_partial_file_from_a_failed_write(tmp_path):
    """A write that fails after the file is opened (here, content that cannot be
    UTF-8 encoded) leaves a partial file on disk. Rollback must unlink it, so the
    ``ApplyError`` "the project is unchanged" claim holds. Guards the regression
    where the target was tracked only after a successful write."""
    (tmp_path / "keep.txt").write_text("pre-existing\n")

    plan = ChangePlan(
        operations=(
            # A lone surrogate cannot encode to UTF-8; write_text opens (creates)
            # the file, then raises while encoding, leaving an empty file behind.
            CreateFileOperation(path="src/pkg/broken.py", content="a\ud800b"),
        ),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "rolled back" in str(excinfo.value)
    # No orphan file and no orphan directory: the partial write was undone.
    assert not (tmp_path / "src/pkg/broken.py").exists()
    assert not (tmp_path / "src").exists()
    assert _snapshot(tmp_path) == before


def test_absolute_path_is_refused_and_writes_nothing(tmp_path):
    """An absolute op.path would escape the project root (root / '/abs' == '/abs').
    Refuse it up front, before any write."""
    outside = tmp_path.parent / "escaped.py"
    plan = ChangePlan(
        operations=(CreateFileOperation(path=str(outside), content="nope\n"),),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "absolute path" in str(excinfo.value)
    assert not outside.exists()
    assert _snapshot(tmp_path) == before


def test_absolute_path_inside_the_root_is_still_refused(tmp_path):
    """Operation paths are relative, and an absolute path that happens to point
    inside the project is no exception. The containment check alone would wave it
    through, because ``root / '/root/src/a.py'`` resolves back under the root."""
    plan = ChangePlan(
        operations=(
            CreateFileOperation(path=str(tmp_path / "src/a.py"), content="nope\n"),
        ),
    )

    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "absolute path" in str(excinfo.value)
    assert "must be relative" in str(excinfo.value)
    assert _snapshot(tmp_path) == {}


def test_parent_escaping_path_is_refused_and_writes_nothing(tmp_path):
    """A path that climbs out with ``..`` is refused, so a create never lands
    above the project root."""
    root = tmp_path / "project"
    root.mkdir()
    plan = ChangePlan(
        operations=(CreateFileOperation(path="../escaped.py", content="nope\n"),),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(root), plan)

    assert "outside the project root" in str(excinfo.value)
    assert not (tmp_path / "escaped.py").exists()
    assert _snapshot(tmp_path) == before


def test_a_rollback_that_cannot_remove_a_file_says_so(tmp_path):
    """Rollback is best-effort, so the error must not promise an unchanged tree
    it did not deliver. Here the unlink fails the way a read-only parent
    directory makes it fail, which also leaves the directory non-empty so its
    rmdir fails too: the message names both instead of claiming "unchanged"."""
    real_unlink = Path.unlink

    def refuse_unlink(self, *args, **kwargs):
        if self.name == "one.py":
            raise PermissionError(13, "Permission denied", str(self))
        return real_unlink(self, *args, **kwargs)

    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="pkg/one.py", content="op one\n"),
            # pkg/one.py is a file, so writing under it fails and trips rollback.
            CreateFileOperation(path="pkg/one.py/nested.py", content="op two\n"),
        ),
    )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "unlink", refuse_unlink)
        with pytest.raises(ApplyError) as excinfo:
            apply_plan(str(tmp_path), plan)

    message = str(excinfo.value)
    assert "could not remove everything" in message
    assert "the project is unchanged" not in message
    # Both leftovers are named, files first: the file it could not unlink and the
    # directory it could not empty. The user knows exactly what to clean up.
    assert f"{tmp_path / 'pkg/one.py'}, {tmp_path / 'pkg'}" in message
    # And they really are still there.
    assert (tmp_path / "pkg/one.py").read_text() == "op one\n"
    assert (tmp_path / "pkg").is_dir()


def test_non_string_path_is_refused(tmp_path):
    """A hand-built op with a non-string path is rejected with a clear ApplyError
    rather than a raw TypeError escaping the applier."""
    plan = ChangePlan(
        operations=(CreateFileOperation(path=None, content="x\n"),),  # type: ignore[arg-type]
    )

    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "string path" in str(excinfo.value)
    assert _snapshot(tmp_path) == {}


def test_non_string_content_is_refused(tmp_path):
    """A hand-built op with non-string content is rejected with a clear ApplyError
    rather than a raw TypeError escaping the applier mid-write."""
    plan = ChangePlan(
        operations=(CreateFileOperation(path="src/pkg/thing.py", content=None),),  # type: ignore[arg-type]
    )

    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "string content" in str(excinfo.value)
    assert _snapshot(tmp_path) == {}


def test_duplicate_paths_in_one_plan_are_refused(tmp_path):
    """Two ops writing the same path would both clear pre-flight and the second
    would truncate the first; refuse the plan instead of silently overwriting."""
    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/thing.py", content="first\n"),
            CreateFileOperation(path="src/pkg/thing.py", content="second\n"),
        ),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "twice" in str(excinfo.value)
    assert not (tmp_path / "src/pkg/thing.py").exists()
    assert _snapshot(tmp_path) == before


def test_differently_spelled_duplicate_paths_are_refused(tmp_path):
    """``a.py``, ``./a.py`` and ``dir/../a.py`` are one file. Comparing raw path
    strings would miss that and let the second op truncate the first, so the
    duplicate check compares resolved targets."""
    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/thing.py", content="first\n"),
            CreateFileOperation(path="./src/pkg/thing.py", content="second\n"),
            CreateFileOperation(path="src/pkg/sub/../thing.py", content="third\n"),
        ),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "twice" in str(excinfo.value)
    assert not (tmp_path / "src/pkg/thing.py").exists()
    assert _snapshot(tmp_path) == before


def test_case_variant_paths_on_a_case_sensitive_filesystem_are_distinct(tmp_path):
    """Where the platform's ``os.path.normcase`` does not fold case (POSIX),
    ``Thing.py`` and ``thing.py`` are two files, not a duplicate, so both are
    written. On Windows, where ``normcase`` lowercases, the same plan is refused
    as a duplicate instead (the next test)."""
    if os.path.normcase("A") == os.path.normcase("a"):
        pytest.skip("platform folds path case (e.g. Windows)")

    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/Thing.py", content="upper\n"),
            CreateFileOperation(path="src/pkg/thing.py", content="lower\n"),
        ),
    )

    written = apply_plan(str(tmp_path), plan)

    assert written == ("src/pkg/Thing.py", "src/pkg/thing.py")
    assert (tmp_path / "src/pkg/Thing.py").read_text() == "upper\n"
    assert (tmp_path / "src/pkg/thing.py").read_text() == "lower\n"


def test_case_variant_paths_where_the_platform_folds_case_are_refused(tmp_path):
    """Where ``os.path.normcase`` folds case (Windows), ``Thing.py`` and
    ``thing.py`` are one file, so the second op is refused as the duplicate it is
    rather than silently truncating the first."""
    if os.path.normcase("A") != os.path.normcase("a"):
        pytest.skip("platform is case-sensitive per os.path.normcase (POSIX)")

    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="src/pkg/Thing.py", content="upper\n"),
            CreateFileOperation(path="src/pkg/thing.py", content="lower\n"),
        ),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(tmp_path), plan)

    assert "twice" in str(excinfo.value)
    assert _snapshot(tmp_path) == before


def test_missing_project_directory_is_refused_and_creates_nothing(tmp_path):
    """The applier writes into a project, it never creates one. A mistyped path
    is refused instead of having parent creation conjure the whole tree."""
    missing = tmp_path / "typo-project"
    plan = ChangePlan(
        operations=(CreateFileOperation(path="src/pkg/thing.py", content="x\n"),),
    )

    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(missing), plan)

    assert "existing project directory" in str(excinfo.value)
    assert not missing.exists()
    assert _snapshot(tmp_path) == {}


def test_project_path_that_is_a_file_is_refused(tmp_path):
    """A path that names a file is not a project root either; refuse it up front
    rather than failing later with a raw ``NotADirectoryError``."""
    not_a_dir = tmp_path / "domain.py"
    not_a_dir.write_text("handwritten\n")
    plan = ChangePlan(
        operations=(CreateFileOperation(path="thing.py", content="x\n"),),
    )

    before = _snapshot(tmp_path)
    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(not_a_dir), plan)

    assert "not a directory" in str(excinfo.value)
    assert _snapshot(tmp_path) == before


def test_empty_plan_on_a_missing_project_is_refused(tmp_path):
    """The check runs before the plan is looked at, so even an empty plan does
    not quietly accept a path that is not a project."""
    missing = tmp_path / "typo-project"

    with pytest.raises(ApplyError) as excinfo:
        apply_plan(str(missing), ChangePlan())

    assert "existing project directory" in str(excinfo.value)
    assert not missing.exists()
