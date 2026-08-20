"""Apply a :class:`~protean.scaffold.ChangePlan` to a project, atomically.

:func:`apply_plan` writes a plan's files to disk, all-or-nothing. It is
create-only for now: an ``add`` plan holds only :class:`CreateFileOperation`\\ s,
and applying edits and config patches is separate later work, so this applier
rejects any other operation up front.

The contract is that a failed apply leaves the tree exactly as it found it:

- **Reject non-creates.** A plan with an edit or a config op is refused before
  anything is written.
- **Pre-flight conflicts.** Every target is checked first. If any target already
  exists, the whole apply is refused, so a create never clobbers hand-written
  code and a partial apply never happens because a later file was in the way.
- **Roll back on failure.** If a write fails partway, the files written so far
  are deleted and the directories this call created are removed (deepest-first,
  only if empty), then an :class:`ApplyError` is raised. Rollback touches only
  paths this call created, so a pre-existing ``src/<package>/`` is left alone.

On success it returns the tuple of written paths (the plan's relative paths, in
plan order) so the caller can report what it wrote.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from protean.scaffold.change_plan import ChangePlan, CreateFileOperation

__all__ = ["ApplyError", "apply_plan"]


class ApplyError(Exception):
    """A user-facing apply failure: an unsupported operation, a target that
    already exists, or an I/O error mid-write. The CLI turns this into a clear
    message and a failure exit code, so the message is written to be read by a
    human. When it wraps a mid-write error, the tree has already been rolled
    back to its pre-apply state."""


def apply_plan(project_path: str, plan: ChangePlan) -> tuple[str, ...]:
    """Apply *plan* under *project_path*, atomically and create-only.

    *project_path* is the project root (the directory that holds ``src/``). Every
    operation's ``path`` is relative to it.

    Returns the tuple of relative paths written, in plan order. An empty plan
    writes nothing and returns an empty tuple.

    Raises :class:`ApplyError` when the plan contains a non-create operation,
    when any target file already exists (checked before any write), or when a
    write fails partway (after rolling the tree back to its pre-apply state).
    """
    root = Path(project_path)

    # 1. Reject non-create operations up front. Editing files and patching config
    #    are separate later work; this applier only creates files.
    creates: list[CreateFileOperation] = []
    for op in plan.operations:
        if not isinstance(op, CreateFileOperation):
            raise ApplyError(
                f"apply supports create operations only, but the plan contains a "
                f"{op.kind!r} operation. Editing files and patching config are "
                "not applied yet."
            )
        creates.append(op)

    # 2. Pre-flight: refuse if any target already exists, before writing anything.
    #    Checking every op before any write is what keeps a later conflict from
    #    leaving an earlier file half-applied on disk.
    for op in creates:
        if (root / op.path).exists():
            raise ApplyError(
                f"apply would overwrite an existing path: {op.path!r}. Refusing "
                "to clobber it; apply is create-only and all-or-nothing. Remove "
                "the file or apply into a clean project."
            )

    # 3. Write, tracking every file and directory this call creates so a failure
    #    can be rolled back to exactly the pre-apply tree.
    written: list[Path] = []
    created_dirs: list[Path] = []
    try:
        for op in creates:
            target = root / op.path
            _ensure_parents(target.parent, created_dirs)
            target.write_text(op.content, encoding="utf-8")
            written.append(target)
    except Exception as exc:
        _rollback(written, created_dirs)
        raise ApplyError(
            f"apply failed and was rolled back; the project is unchanged. Cause: {exc}"
        ) from exc

    return tuple(op.path for op in creates)


def _ensure_parents(directory: Path, created_dirs: list[Path]) -> None:
    """Create *directory* and any missing ancestors, recording each one made.

    Walks up from *directory* until it reaches an existing path, then creates the
    missing directories shallowest-first, appending each to *created_dirs* as it
    is made. Recording only the directories this call actually creates is what
    lets rollback remove exactly them and never a pre-existing ancestor. A
    ``mkdir`` under a path that is an existing file raises ``NotADirectoryError``,
    which the caller turns into a rollback.
    """
    missing: list[Path] = []
    current = directory
    while not current.exists():
        missing.append(current)
        parent = current.parent
        if parent == current:
            # Reached the filesystem root; nothing more to walk.
            break
        current = parent

    # ``missing`` is deepest-first; create shallowest-first so each parent exists
    # before its child.
    for dir_path in reversed(missing):
        dir_path.mkdir()
        created_dirs.append(dir_path)


def _rollback(written: list[Path], created_dirs: list[Path]) -> None:
    """Undo a partial apply: delete the files written, then remove the directories
    this call created.

    Files go first (reverse order), then directories deepest-first and only if
    empty, so a directory this call made is removed once its files are gone but a
    directory that already held other content is left intact. Best-effort: a
    failure to remove one path never masks the original error the caller is about
    to raise.
    """
    for file_path in reversed(written):
        with contextlib.suppress(OSError):
            file_path.unlink()

    # ``created_dirs`` was appended shallowest-first as directories were made;
    # remove deepest-first so a child directory is gone before its parent.
    for dir_path in reversed(created_dirs):
        with contextlib.suppress(OSError):
            dir_path.rmdir()
