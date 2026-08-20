"""Apply a :class:`~protean.scaffold.ChangePlan` to a project, atomically.

:func:`apply_plan` writes a plan's files to disk, all-or-nothing. It is
create-only for now: an ``add`` plan holds only :class:`CreateFileOperation`\\ s,
and applying edits and config patches is separate later work, so this applier
rejects any other operation up front.

The contract is that a failed apply leaves the tree exactly as it found it:

- **Require an existing project.** A *project_path* that is not a directory is
  refused, so a mistyped path never has a project tree created for it.
- **Reject non-creates.** A plan with an edit or a config op is refused before
  anything is written.
- **Pre-flight conflicts.** Every target is checked first. If any target already
  exists, the whole apply is refused, so a create never clobbers hand-written
  code and a partial apply never happens because a later file was in the way.
- **Roll back on failure.** If a write fails partway, the files written so far
  are deleted and the directories this call created are removed (deepest-first,
  only if empty), then an :class:`ApplyError` is raised. Rollback touches only
  paths this call created, so a pre-existing ``src/<package>/`` is left alone.
  Removal itself is best-effort, so anything rollback could not remove (a
  permission error, say) is named in the error rather than glossed over.

On success it returns the tuple of written paths (the plan's relative paths, in
plan order) so the caller can report what it wrote.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from protean.scaffold.change_plan import ChangePlan, CreateFileOperation

__all__ = ["ApplyError", "apply_plan"]


def _exists(path: Path) -> bool:
    """True if something is on disk at *path*, a broken symlink included.

    ``Path.exists()`` follows the link and returns ``False`` for a symlink whose
    target is missing, so a dangling link reads as a free path. That would let
    the pre-flight write through it and let rollback under-report one left
    behind. ``is_symlink()`` is ``True`` for a broken link, so the two together
    mean "a path is here", which is what the conflict pre-flight, the parent
    walk, and rollback all need.
    """
    return path.exists() or path.is_symlink()


def _fs_folds_case(root: Path) -> bool:
    """Does the filesystem holding *root* fold path case?

    True on a case-insensitive filesystem (default macOS APFS, Windows, a
    case-insensitive mount), False on a case-sensitive one (typical Linux). It
    asks the filesystem directly, without touching disk: whether a case-flipped
    spelling of *root* reaches the same directory. ``samefile`` is true only when
    both spellings resolve to one directory, which is what case folding means; on
    a case-sensitive filesystem the flipped spelling does not exist and it raises.
    An absolute project root always carries a cased character to flip.
    """
    swapped = str(root).swapcase()
    try:
        return os.path.samefile(root, swapped)
    except OSError:
        return False


class ApplyError(Exception):
    """A user-facing apply failure: a project directory that does not exist, an
    unsupported operation, a target that already exists, or an I/O error
    mid-write. The CLI turns this into a clear message and a failure exit code,
    so the message is written to be read by a human. When it wraps a mid-write
    error, rollback has already run: the message says the project is unchanged
    when rollback removed everything, and otherwise lists what is still on
    disk."""


def apply_plan(project_path: str, plan: ChangePlan) -> tuple[str, ...]:
    """Apply *plan* under *project_path*, atomically and create-only.

    *project_path* is the project root, an existing directory. The applier writes
    into it, it does not create it, and it makes any missing directory on the way
    to a target (a ``src/<package>/`` a create needs, say). Every operation's
    ``path`` is relative to this root.

    Returns the tuple of relative paths written, in plan order. An empty plan
    writes nothing and returns an empty tuple.

    Raises :class:`ApplyError` when *project_path* is not an existing directory,
    when the plan contains a non-create operation, when any target file already
    exists (checked before any write), or when a write fails partway (after
    rolling the tree back to its pre-apply state, as far as removal succeeds).
    """
    root = Path(project_path)
    # The applier writes into a project that already exists; it never creates one.
    # Parent creation below makes any missing directory on the way to a target, so
    # without this check a mistyped path would have the whole tree conjured up
    # somewhere the caller never meant to write.
    if not root.is_dir():
        raise ApplyError(
            f"apply needs an existing project directory, but {project_path!r} is "
            "not a directory."
        )
    root_resolved = root.resolve()

    # Whether two case-variant targets (``Thing.py`` / ``thing.py``) are one file
    # depends on the filesystem, not the platform, so probe the actual one holding
    # the project. On a case-insensitive filesystem the second create would
    # truncate the first past a duplicate check that keyed on the raw string.
    fold_case = _fs_folds_case(root_resolved)

    # 1. Validate every operation up front, before any write. A create-only,
    #    within-root, well-typed, duplicate-free plan is the precondition for the
    #    atomic write below; anything else is refused here so nothing lands on
    #    disk. Editing files and patching config are separate later work.
    creates: list[CreateFileOperation] = []
    seen_targets: set[str] = set()
    for op in plan.operations:
        if not isinstance(op, CreateFileOperation):
            raise ApplyError(
                f"apply supports create operations only, but the plan contains a "
                f"{op.kind!r} operation. Editing files and patching config are "
                "not applied yet."
            )
        # A hand-built or JSON-loaded op can carry a non-string path/content that
        # would blow up as a raw TypeError mid-apply (outside the rollback). Reject
        # it here with a clear message instead.
        if not isinstance(op.path, str):
            raise ApplyError(
                f"apply needs a string path, got {type(op.path).__name__}."
            )
        if not isinstance(op.content, str):
            raise ApplyError(
                f"apply needs string content for {op.path!r}, got "
                f"{type(op.content).__name__}."
            )
        # Operation paths are relative to the project root, so an absolute path
        # is refused here. ``root / "/abs"`` discards the root, so the containment
        # check below cannot catch an absolute path that happens to point inside
        # the project; only this check enforces the relative-path contract.
        # ``drive`` also covers the Windows drive-relative form (``C:file.py``),
        # which is not absolute but is not root-relative either.
        candidate = Path(op.path)
        if candidate.is_absolute() or candidate.drive:
            raise ApplyError(
                f"apply refuses an absolute path: {op.path!r}. Operation paths "
                "must be relative to the project root."
            )
        # Keep every write inside the project root. A path that climbs out with
        # ``..`` would otherwise write anywhere on the filesystem.
        target = (root / op.path).resolve()
        if not target.is_relative_to(root_resolved):
            raise ApplyError(
                f"apply refuses a path outside the project root: {op.path!r}. "
                "Operation paths must stay under the project."
            )
        # Two ops writing the same path would both clear pre-flight (neither is on
        # disk yet) and the second would silently truncate the first. Refuse it.
        # Key on the resolved target, so spellings of one file (``a.py``,
        # ``./a.py``, ``dir/../a.py``) count as the duplicate they are; casefold
        # the key where the filesystem folds case, so ``Thing.py`` and ``thing.py``
        # do too there while staying distinct on a case-sensitive filesystem.
        resolved = str(target)
        key = resolved.casefold() if fold_case else resolved
        if key in seen_targets:
            raise ApplyError(f"apply refuses a plan that writes {op.path!r} twice.")
        seen_targets.add(key)
        creates.append(op)

    # 2. Pre-flight: refuse if any target already exists, before writing anything.
    #    Checking every op before any write is what keeps a later conflict from
    #    leaving an earlier file half-applied on disk.
    for op in creates:
        if _exists(root / op.path):
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
            # Track the target *before* the write. ``write_text`` opens the file
            # (creating it) before it encodes and writes the content, so a failure
            # mid-write can leave an empty file behind. Recording it first is what
            # lets rollback unlink that partial file. A recorded path that never
            # got created is a no-op for rollback (the unlink is suppressed).
            written.append(target)
            target.write_text(op.content, encoding="utf-8")
    except Exception as exc:
        # Rollback is best-effort, so it reports what it could not remove and
        # the error names those paths instead of claiming an unchanged project.
        leftover = _rollback(written, created_dirs)
        if leftover:
            paths = ", ".join(str(path) for path in leftover)
            raise ApplyError(
                f"apply failed, and rollback could not remove everything it had "
                f"written. Still on disk: {paths}. Remove them before retrying. "
                f"Cause: {exc}"
            ) from exc
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
    while not _exists(current):
        missing.append(current)
        parent = current.parent
        if parent == current:  # pragma: no cover - the filesystem root always
            # exists, so the while loop exits before this guard can fire; it is a
            # defensive backstop against an infinite walk, not a reachable path.
            break
        current = parent

    # ``missing`` is deepest-first; create shallowest-first so each parent exists
    # before its child.
    for dir_path in reversed(missing):
        dir_path.mkdir()
        created_dirs.append(dir_path)


def _rollback(written: list[Path], created_dirs: list[Path]) -> tuple[Path, ...]:
    """Undo a partial apply: delete the files written, then remove the directories
    this call created. Returns the paths still on disk afterwards.

    Files go first (reverse order), then directories deepest-first and only if
    empty, so a directory this call made is removed once its files are gone but a
    directory that already held other content is left intact. Removal is
    best-effort: a failure to remove one path (a permission error, say) never
    masks the original error the caller is about to raise. Those paths come back
    in the return value instead, so the caller can name them rather than claim a
    clean tree. A recorded path that was never created is not leftover: removing
    it raises ``FileNotFoundError`` and it is not on disk.
    """
    leftover: list[Path] = []

    for file_path in reversed(written):
        with contextlib.suppress(OSError):
            file_path.unlink()
        if _exists(file_path):
            leftover.append(file_path)

    # ``created_dirs`` was appended shallowest-first as directories were made;
    # remove deepest-first so a child directory is gone before its parent.
    for dir_path in reversed(created_dirs):
        with contextlib.suppress(OSError):
            dir_path.rmdir()
        if _exists(dir_path):
            leftover.append(dir_path)

    return tuple(leftover)
