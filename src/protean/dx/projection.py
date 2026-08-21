"""An idempotent file-projection engine for ``protean dx``.

The engine writes a rendered artifact into a user's project and can re-write it
later without clobbering the user's own edits. It is the update-and-merge path
that :func:`~protean.scaffold.apply.apply_plan` defers: ``apply_plan`` is
create-only, so this engine composes with it for the create case and adds the
merge, diff, and conflict-detection the re-projection case needs.

Two merge modes cover the file shapes ``protean dx`` ships:

- **Managed region** (text). The framework block sits between two
  sentinel-comment markers, ``PROTEAN:BEGIN <region-id>`` and
  ``PROTEAN:END <region-id>``. Re-projecting replaces only the body between the
  markers and leaves every byte outside untouched. The caller passes the comment
  syntax (``<!-- -->`` for AGENTS.md, ``#`` for a config), so the engine stays
  format-agnostic.
- **Structured JSON**. The rendered dict's top-level keys are the managed keys.
  Re-projecting sets those keys and preserves every other key on disk. This is
  for ``.mcp.json``.

A lockfile at ``.protean/dx.lock`` records, per target path, the pack version
stamp and two hashes: the hash of the whole file the engine last wrote and the
hash of the managed slice it last wrote. The slice hash drives the diff decision
below (does the user's on-disk region still match what the engine wrote). The
whole-file hash is not consulted by that decision; it feeds only
``outside_modified``, the signal that the file drifted around an untouched region.
The diff decision:

- ``CREATE``: the target is absent.
- ``NO_CHANGE``: the on-disk slice equals the newly rendered slice and the
  version stamp matches. The no-op case; the lockfile is left untouched.
- ``UPDATE``: a safe write. Either the user left the region alone (on-disk slice
  equals what the lock last recorded) or the on-disk slice already equals the new
  content while the version stamp advanced.
- ``CONFLICT``: the on-disk slice differs from both the lock's last-written slice
  and the newly rendered slice, so the user edited inside the framework's
  territory. The engine writes nothing and surfaces the conflict.

Serialization follows the IR house style (see
:mod:`protean.scaffold.change_plan`): frozen dataclasses, an explicit
``to_dict``/``from_dict`` JSON dump with sorted keys and a trailing newline, and
a ``lock_version`` marker that ``from_dict`` rejects loudly when it does not
understand it.

Line endings: the engine reads a target in text mode, so whatever the file uses
on disk arrives as ``\\n``, and every hash is taken over that utf-8-encoded,
LF-normalized text. A CRLF checkout of the same content therefore hashes the same
as an LF one and a benign platform newline difference never reads as a phantom
conflict. Writes go back out in whatever line ending the file already uses, so an
update never rewrites a file's line endings.

See ADR-0036 for the decision record behind the lockfile and the two merge modes.

Design decisions for v1:

- **One named region per file.** A managed-region target carries exactly one
  ``PROTEAN:BEGIN/END`` pair. A missing, duplicated, or reversed marker raises
  rather than silently overwriting the whole file.
- **Shallow JSON merge.** The managed top-level keys are replaced whole; every
  other key, nested structure included, is preserved. ``.mcp.json`` names its
  servers at the top level, so a shallow merge is enough.

Usage::

    from pathlib import Path
    from protean.dx import ManagedRegionProjection, apply_projection

    projection = ManagedRegionProjection(
        target="AGENTS.md",
        version="0.1.0",
        region_id="protean",
        body="Framework-owned guidance.",
        comment_prefix="<!-- ",
        comment_suffix=" -->",
    )
    result = apply_projection(Path("my_project"), projection)
    assert result.status.value in {"create", "update", "no_change"}
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from protean.scaffold.apply import apply_plan
from protean.scaffold.change_plan import (
    OWNERSHIP_GENERATED,
    ChangePlan,
    CreateFileOperation,
)

__all__ = [
    "LOCK_VERSION",
    "ManagedRegionProjection",
    "Projection",
    "ProjectionConflict",
    "ProjectionEntry",
    "ProjectionError",
    "ProjectionLock",
    "ProjectionMode",
    "ProjectionResult",
    "ProjectionStatus",
    "StructuredJsonProjection",
    "apply_projection",
    "diff_projection",
    "load_lock",
]

# The version marker carried on every serialized lockfile. Bumped when the
# serialized shape changes incompatibly; a ``lock_version`` the code does not
# understand is rejected loudly by :meth:`ProjectionLock.from_dict`.
LOCK_VERSION = "1.0"

_LOCK_DIR = ".protean"
_LOCK_FILENAME = "dx.lock"

# The fixed marker keywords. The caller wraps them in its own comment syntax.
_MARKER_BEGIN = "PROTEAN:BEGIN"
_MARKER_END = "PROTEAN:END"

# How much of a file to read when sniffing which line ending it uses.
_NEWLINE_SNIFF_BYTES = 8192


class ProjectionError(Exception):
    """A file-projection failure the caller is meant to read and act on.

    Raised for a malformed managed-region target (a missing, duplicated, or
    reversed marker), a target that is not the JSON object a structured merge
    needs, or a corrupt lockfile. :class:`ProjectionConflict` is the subclass for
    the specific case of a user edit inside the framework's territory.
    """


class ProjectionConflict(ProjectionError):
    """The user edited inside the managed slice, so a re-projection is refused.

    Carries the *target* path and a *region* description (the region id for a
    managed-region target, the managed key names for a structured-JSON target) so
    a ``check`` or ``diff`` verb can report exactly what conflicts.
    """

    def __init__(self, target: str, region: str) -> None:
        self.target = target
        self.region = region
        super().__init__(
            f"Projection conflict at {target!r}: the managed region {region!r} was "
            "edited outside the framework, and the edit differs from the incoming "
            "content. Refusing to overwrite it; resolve the edit and re-run."
        )


class ProjectionMode(StrEnum):
    """The merge mode a projection applies."""

    MANAGED_REGION = "managed_region"
    """Replace the body between two sentinel-comment markers in a text file."""

    STRUCTURED_JSON = "structured_json"
    """Set the managed top-level keys of a JSON object and preserve the rest."""


class ProjectionStatus(StrEnum):
    """Outcome of a diff or apply."""

    CREATE = "create"
    """The target is absent; the engine would create it."""

    NO_CHANGE = "no_change"
    """On-disk slice matches the new slice and the version stamp matches."""

    UPDATE = "update"
    """A safe write: the region is untouched, or already equals the new content."""

    CONFLICT = "conflict"
    """The on-disk slice was edited to something neither the lock nor the render
    expects. The engine writes nothing."""


@dataclass(frozen=True)
class ManagedRegionProjection:
    """A managed-region (text) projection request.

    ``comment_prefix`` and ``comment_suffix`` wrap the marker keyword: HTML passes
    ``"<!-- "`` and ``" -->"``, a ``#``-comment config passes ``"# "`` and ``""``.
    The begin marker line is therefore ``<prefix>PROTEAN:BEGIN <region_id><suffix>``.
    """

    target: str
    version: str
    region_id: str
    body: str
    comment_prefix: str
    comment_suffix: str = ""

    def __post_init__(self) -> None:
        if not self.region_id:
            raise ValueError("region_id must be a non-empty string")
        # The markers are single lines, so any part of them carrying a newline
        # would split the marker across lines and break the parse.
        for name, value in (
            ("region_id", self.region_id),
            ("comment_prefix", self.comment_prefix),
            ("comment_suffix", self.comment_suffix),
        ):
            if "\n" in value:
                raise ValueError(f"{name} must not contain a newline")
        # A body line identical to a marker line would frame a second, phantom
        # region and poison every later re-projection (the parse would count two
        # markers). Reject it at construction rather than write a self-poisoning
        # file.
        marker_lines = {self.begin_marker, self.end_marker}
        for line in self.body.split("\n"):
            if line in marker_lines:
                raise ValueError(
                    "body must not contain a line identical to a region marker "
                    f"({line!r}); it would frame a phantom region."
                )

    @property
    def mode(self) -> ProjectionMode:
        return ProjectionMode.MANAGED_REGION

    @property
    def begin_marker(self) -> str:
        """The full begin-marker line, comment syntax included."""
        return f"{self.comment_prefix}{_MARKER_BEGIN} {self.region_id}{self.comment_suffix}"

    @property
    def end_marker(self) -> str:
        """The full end-marker line, comment syntax included."""
        return (
            f"{self.comment_prefix}{_MARKER_END} {self.region_id}{self.comment_suffix}"
        )


@dataclass(frozen=True)
class StructuredJsonProjection:
    """A structured-JSON projection request.

    ``data`` is the rendered dict. Its top-level keys are the managed keys: a
    re-projection sets them and preserves every other key on disk. ``data`` must
    be non-empty, since an empty managed set would manage nothing.
    """

    target: str
    version: str
    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.data:
            raise ValueError("data must name at least one managed key")
        # The managed values are hashed and written as JSON, so they must be
        # JSON-serializable with string keys. Catch a non-serializable value
        # (a ``set``, ``bytes``) or a bad key here rather than raise a raw
        # ``TypeError`` deep in the diff path.
        try:
            _canonical_json(dict(self.data))
        except TypeError as exc:
            raise ValueError(
                f"data must be JSON-serializable with string keys: {exc}"
            ) from exc

    @property
    def mode(self) -> ProjectionMode:
        return ProjectionMode.STRUCTURED_JSON

    @property
    def managed_keys(self) -> tuple[str, ...]:
        """The managed top-level keys, in the render's order."""
        return tuple(self.data.keys())


# The projection union. The engine dispatches on the concrete type.
Projection = ManagedRegionProjection | StructuredJsonProjection


@dataclass(frozen=True)
class ProjectionEntry:
    """One target's row in the lockfile: the version stamp and the two hashes."""

    version: str
    file_hash: str
    slice_hash: str

    def to_dict(self) -> dict[str, str]:
        """Serialize to a JSON-ready dict."""
        return {
            "version": self.version,
            "file_hash": self.file_hash,
            "slice_hash": self.slice_hash,
        }

    @classmethod
    def from_dict(cls, data: Any, target: str) -> ProjectionEntry:
        """Rebuild an entry, validating the shape and field types.

        A malformed entry (a non-object, a missing field, or a non-string value)
        fails loud rather than being coerced into a valid-looking entry.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"lock entry for {target!r} must be an object, got {type(data).__name__}"
            )
        return cls(
            version=_require_str(data, "version", f"lock entry {target!r}"),
            file_hash=_require_str(data, "file_hash", f"lock entry {target!r}"),
            slice_hash=_require_str(data, "slice_hash", f"lock entry {target!r}"),
        )


@dataclass(frozen=True)
class ProjectionLock:
    """The lockfile: a map from target path to its :class:`ProjectionEntry`."""

    entries: dict[str, ProjectionEntry] = field(default_factory=dict)

    def with_entry(self, target: str, entry: ProjectionEntry) -> ProjectionLock:
        """Return a new lock with *target*'s entry set to *entry*."""
        new_entries = dict(self.entries)
        new_entries[target] = entry
        return ProjectionLock(entries=new_entries)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict, carrying the ``lock_version`` marker.

        Entries are emitted in sorted-key order so the persisted file is stable.
        """
        return {
            "lock_version": LOCK_VERSION,
            "entries": {
                path: self.entries[path].to_dict() for path in sorted(self.entries)
            },
        }

    @classmethod
    def from_dict(cls, data: Any) -> ProjectionLock:
        """Rebuild a lock from its serialized dict.

        Raises :exc:`ValueError` on a non-object payload, on a ``lock_version`` the
        code does not understand, on a non-object ``entries`` map, or on a
        malformed entry. A corrupt or newer lockfile fails loud.
        """
        if not isinstance(data, dict):
            raise ValueError("A serialized ProjectionLock must be a mapping")
        version = data.get("lock_version")
        if version != LOCK_VERSION:
            raise ValueError(
                f"Unsupported lock_version: {version!r}. "
                f"This build understands {LOCK_VERSION!r}."
            )
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, dict):
            raise ValueError("ProjectionLock 'entries' must be an object")
        entries = {
            str(target): ProjectionEntry.from_dict(entry, str(target))
            for target, entry in raw_entries.items()
        }
        return cls(entries=entries)


@dataclass(frozen=True)
class ProjectionResult:
    """The outcome of a diff or apply. Mutates nothing on its own.

    ``content`` is the full file text the engine would write (``CREATE``) or did
    write (``UPDATE``); it is ``None`` for ``NO_CHANGE`` and ``CONFLICT``.
    ``file_hash`` is the hash of that content, ``None`` when ``content`` is.
    ``slice_hash`` is the hash of the newly rendered managed slice.
    ``outside_modified`` is ``True`` when the file drifted from the lock's
    recorded file hash while the managed slice stayed the same, so the drift is
    entirely outside the managed region. It is informational (a ``check`` or
    ``diff`` verb can report a user edit around the region) and does not by itself
    trigger a write.
    """

    target: str
    status: ProjectionStatus
    version: str
    slice_hash: str
    content: str | None = None
    file_hash: str | None = None
    outside_modified: bool = False


def _require_str(data: dict[str, Any], key: str, context: str) -> str:
    """Return ``data[key]`` as a string, or raise a clear :exc:`ValueError`.

    Checks both presence and type, so a malformed lockfile fails loud instead of
    being coerced into a valid-looking string.
    """
    if key not in data:
        raise ValueError(f"{context} is missing required field {key!r}")
    value = data[key]
    if not isinstance(value, str):
        raise ValueError(
            f"{context} field {key!r} must be a string, got {type(value).__name__}"
        )
    return value


def _hash_text(text: str) -> str:
    """Hash *text* over its utf-8 bytes.

    *text* always comes from a text-mode read or the engine's own rendering, so its
    line endings are already LF whatever the file holds on disk. Fixed utf-8 over
    that, so the hash is stable across platforms and a benign newline difference
    never reads as a phantom conflict.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    """Serialize *obj* to a canonical JSON string for hashing.

    Sorted keys and the tightest separators, so two equal structures always
    serialize to the same bytes whatever order the producer built them in.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _marker_line_positions(text: str, marker: str) -> list[int]:
    """Return the start offsets where *marker* occupies a whole line of *text*.

    The match is line-anchored: *marker* must start at the beginning of the file
    or just after a newline, and end at the end of the file or just before a
    newline. A plain substring (a marker keyword mentioned mid-line, or a shorter
    region id that is a prefix of a longer one) is not counted.
    """
    positions: list[int] = []
    start = 0
    while True:
        idx = text.find(marker, start)
        if idx == -1:
            break
        at_line_start = idx == 0 or text[idx - 1] == "\n"
        line_end = idx + len(marker)
        at_line_end = line_end == len(text) or text[line_end] == "\n"
        if at_line_start and at_line_end:
            positions.append(idx)
        start = idx + 1
    return positions


def _find_unique_marker(text: str, marker: str, target: str) -> int:
    """Return the start index of the single whole-line occurrence of *marker*.

    Raises :exc:`ProjectionError` when the marker is absent or appears more than
    once, so a malformed managed-region target is refused rather than silently
    overwritten. Matching is line-anchored (see :func:`_marker_line_positions`),
    so a shorter region id that is a prefix of a longer one does not mismatch.
    v1 supports exactly one region per file.
    """
    positions = _marker_line_positions(text, marker)
    if len(positions) == 0:
        raise ProjectionError(
            f"Managed-region target {target!r} is missing its marker {marker!r}. "
            "Refusing to overwrite the file."
        )
    if len(positions) > 1:
        raise ProjectionError(
            f"Managed-region target {target!r} carries {len(positions)} copies of "
            f"the marker {marker!r}; exactly one is supported. Refusing to overwrite "
            "the file."
        )
    return positions[0]


def _region_bounds(text: str, projection: ManagedRegionProjection) -> tuple[int, int]:
    """Return ``(after_begin, end_start)`` byte offsets of the managed body.

    ``after_begin`` is the offset just past the begin-marker line; ``end_start``
    is the offset where the end-marker line starts. Raises
    :exc:`ProjectionError` when either marker is malformed or the end marker
    precedes the begin marker.
    """
    begin_pos = _find_unique_marker(text, projection.begin_marker, projection.target)
    end_pos = _find_unique_marker(text, projection.end_marker, projection.target)
    if end_pos < begin_pos:
        raise ProjectionError(
            f"Managed-region target {projection.target!r} has its end marker before "
            "its begin marker. Refusing to overwrite the file."
        )
    return begin_pos + len(projection.begin_marker), end_pos


def _extract_region_body(text: str, projection: ManagedRegionProjection) -> str:
    """Return the current body between the markers, minus the framing newlines.

    The engine writes a region as ``<begin>\\n<body>\\n<end>``, so the raw text
    between the markers carries one leading and one trailing newline. Stripping at
    most one of each recovers the body the engine wrote, and reconstructing it the
    same way round-trips.
    """
    after_begin, end_start = _region_bounds(text, projection)
    raw = text[after_begin:end_start]
    if raw.startswith("\n"):
        raw = raw[1:]
    if raw.endswith("\n"):
        raw = raw[:-1]
    return raw


def _merge_region(text: str, projection: ManagedRegionProjection) -> str:
    """Replace the managed body in *text* with the projection's new body.

    Everything outside the markers, the marker lines included, is preserved
    byte-for-byte.
    """
    after_begin, end_start = _region_bounds(text, projection)
    before = text[:after_begin]
    after = text[end_start:]
    return f"{before}\n{projection.body}\n{after}"


def _create_region(projection: ManagedRegionProjection) -> str:
    """Render a fresh managed-region file: just the region, plus a trailing newline."""
    return f"{projection.begin_marker}\n{projection.body}\n{projection.end_marker}\n"


def _parse_json_object(text: str, target: str) -> dict[str, Any]:
    """Parse *text* as a JSON object, or raise :exc:`ProjectionError`.

    A structured merge needs a top-level object; a non-object or invalid JSON
    target fails loud rather than being silently overwritten.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectionError(
            f"Structured-JSON target {target!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ProjectionError(
            f"Structured-JSON target {target!r} must be a JSON object, "
            f"got {type(data).__name__}."
        )
    return data


def _json_disk_slice(disk: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Canonical hash-input for the managed keys' current on-disk values."""
    return _canonical_json({key: disk.get(key) for key in keys})


def _json_new_slice(projection: StructuredJsonProjection) -> str:
    """Canonical hash-input for the newly rendered managed values."""
    return _canonical_json(dict(projection.data))


def _merge_json(disk: dict[str, Any], projection: StructuredJsonProjection) -> str:
    """Shallow-merge the managed keys over *disk* and render the merged file.

    The managed top-level keys are replaced whole; every other key is preserved.
    Rendered with two-space indent, sorted keys, and a trailing newline.
    """
    merged = {**disk, **projection.data}
    return json.dumps(merged, indent=2, sort_keys=True) + "\n"


def _create_json(projection: StructuredJsonProjection) -> str:
    """Render a fresh structured-JSON file from the managed keys alone."""
    return json.dumps(dict(projection.data), indent=2, sort_keys=True) + "\n"


def _decide(
    disk_slice_hash: str,
    lock_slice_hash: str | None,
    new_slice_hash: str,
    version_match: bool,
) -> ProjectionStatus:
    """Classify a re-projection over an existing target.

    The conflict predicate is ``disk != lock and disk != new`` (a lock hash of
    ``None``, meaning no recorded entry, counts as "disk != lock"). Everything that
    is not that predicate and not the pure no-op is a safe write:

    - ``NO_CHANGE``: the slice already equals the new slice and the version stamp
      matches. Nothing to do.
    - ``UPDATE``: the region is untouched (``disk == lock``), or the on-disk slice
      already equals the new content while the version advanced. Both are safe to
      write; the second rewrites identical bytes and advances the lock.
    - ``CONFLICT``: neither. The user edited the slice to something the engine did
      not write and the render does not want.
    """
    if disk_slice_hash == new_slice_hash and version_match:
        return ProjectionStatus.NO_CHANGE
    if lock_slice_hash is not None and disk_slice_hash == lock_slice_hash:
        return ProjectionStatus.UPDATE
    if disk_slice_hash == new_slice_hash:
        return ProjectionStatus.UPDATE
    return ProjectionStatus.CONFLICT


def diff_projection(
    project_root: Path | str, projection: Projection
) -> ProjectionResult:
    """Compute what applying *projection* would do, without touching disk.

    Recomputes the on-disk state, compares it against the lockfile and the newly
    rendered artifact, and returns a :class:`ProjectionResult` carrying the
    status and, for a write, the merged content and its hashes. Mirrors
    :func:`~protean.scaffold.manifest.check_manifest_drift`: derive and compare,
    mutate nothing.

    Raises :exc:`ProjectionError` when the target is a symlink, when a
    managed-region target has a malformed marker, when a structured-JSON target is
    not a JSON object, or when the lockfile is corrupt.
    """
    root = Path(project_root)
    target_path = root / projection.target
    lock = load_lock(root)
    entry = lock.entries.get(projection.target)

    if isinstance(projection, ManagedRegionProjection):
        new_slice = projection.body
        create_content = _create_region(projection)
    else:
        new_slice = _json_new_slice(projection)
        create_content = _create_json(projection)
    new_slice_hash = _hash_text(new_slice)

    if target_path.is_symlink():
        raise ProjectionError(
            f"Target {projection.target!r} is a symlink. Refusing to project onto "
            "it: an update would replace the link with a regular file and leave "
            "the link's target behind."
        )

    if not target_path.exists():
        return ProjectionResult(
            target=projection.target,
            status=ProjectionStatus.CREATE,
            version=projection.version,
            slice_hash=new_slice_hash,
            content=create_content,
            file_hash=_hash_text(create_content),
            outside_modified=False,
        )

    try:
        disk_content = target_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectionError(
            f"Target {projection.target!r} is not valid utf-8: {exc}. "
            "Refusing to overwrite it."
        ) from exc
    if isinstance(projection, ManagedRegionProjection):
        disk_slice = _extract_region_body(disk_content, projection)
        merged = _merge_region(disk_content, projection)
    else:
        disk = _parse_json_object(disk_content, projection.target)
        disk_slice = _json_disk_slice(disk, projection.managed_keys)
        merged = _merge_json(disk, projection)

    disk_slice_hash = _hash_text(disk_slice)
    version_match = entry is not None and entry.version == projection.version
    lock_slice_hash = entry.slice_hash if entry is not None else None
    # The file drifted from what the engine wrote, but the managed slice is
    # untouched, so the drift is entirely outside the managed region.
    outside_modified = (
        entry is not None
        and entry.file_hash != _hash_text(disk_content)
        and disk_slice_hash == entry.slice_hash
    )

    status = _decide(disk_slice_hash, lock_slice_hash, new_slice_hash, version_match)
    writes = status is ProjectionStatus.UPDATE
    return ProjectionResult(
        target=projection.target,
        status=status,
        version=projection.version,
        slice_hash=new_slice_hash,
        content=merged if writes else None,
        file_hash=_hash_text(merged) if writes else None,
        outside_modified=outside_modified,
    )


def apply_projection(
    project_root: Path | str, projection: Projection
) -> ProjectionResult:
    """Apply *projection* under *project_root*, idempotently.

    Runs :func:`diff_projection` first, then acts on the status:

    - ``CONFLICT``: writes nothing and raises :exc:`ProjectionConflict`.
    - ``NO_CHANGE``: does nothing and leaves the lockfile untouched.
    - ``CREATE``: delegates to :func:`~protean.scaffold.apply.apply_plan`, reusing
      its pre-flight and rollback, then records the lock entry.
    - ``UPDATE``: writes the merged file in place (atomically, via a temp file and
      an ``os.replace``), then records the lock entry. The file is written before
      the lock, so a failed write leaves the lock on the prior stamp.

    Returns the :class:`ProjectionResult` from the diff.
    """
    root = Path(project_root)
    result = diff_projection(root, projection)

    if result.status is ProjectionStatus.CONFLICT:
        if isinstance(projection, ManagedRegionProjection):
            region = projection.region_id
        else:
            region = ", ".join(projection.managed_keys)
        raise ProjectionConflict(target=projection.target, region=region)

    if result.status is ProjectionStatus.NO_CHANGE:
        return result

    # CREATE and UPDATE both carry the content to write; narrow for the type
    # checker (CONFLICT and NO_CHANGE, the None-content cases, already returned).
    assert result.content is not None and result.file_hash is not None

    if result.status is ProjectionStatus.CREATE:
        plan = ChangePlan(
            operations=(
                CreateFileOperation(
                    path=projection.target,
                    content=result.content,
                    ownership=OWNERSHIP_GENERATED,
                ),
            )
        )
        apply_plan(str(root), plan)
    else:  # UPDATE
        _atomic_write(root / projection.target, result.content)

    _record_lock(
        root,
        projection.target,
        ProjectionEntry(
            version=result.version,
            file_hash=result.file_hash,
            slice_hash=result.slice_hash,
        ),
    )
    return result


def _detect_newline(path: Path) -> str:
    """Return the newline sequence *path* already uses, ``"\\n"`` when it has none.

    Only the first line ending is inspected, which is enough for the consistent
    files the engine projects into. A missing or unreadable file answers ``"\\n"``:
    the engine's own rendering is LF.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(_NEWLINE_SNIFF_BYTES)
    except OSError:
        return "\n"
    index = head.find(b"\n")
    if index > 0 and head[index - 1 : index] == b"\r":
        return "\r\n"
    return "\n"


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically: a sibling temp file, then a rename.

    ``os.replace`` is atomic within a filesystem, so a failed write leaves the
    prior file intact rather than a half-written one.

    *content* carries LF line endings; they are written back in whatever style the
    file already uses, so an update never rewrites a file's line endings. A default
    text write would translate them to the platform's own ending instead, which on
    Windows flips every line in the file, the ones outside the managed region too.
    """
    tmp = path.with_name(f"{path.name}.dx-tmp")
    newline = _detect_newline(path)
    try:
        with tmp.open("w", encoding="utf-8", newline=newline) as handle:
            handle.write(content)
        os.replace(tmp, path)
    finally:
        # A failed write (or a failed replace) must not leave a stale temp
        # sibling behind. The successful replace already consumed ``tmp``.
        tmp.unlink(missing_ok=True)


def load_lock(project_root: Path | str) -> ProjectionLock:
    """Load the lockfile from ``<project_root>/.protean/dx.lock``.

    Returns an empty :class:`ProjectionLock` when the file is absent, which is how
    a first projection reads. Raises :exc:`ValueError` when the file exists but
    cannot be read, is not valid JSON, or does not carry the lock shape (an
    unknown ``lock_version`` included).
    """
    lock_path = Path(project_root) / _LOCK_DIR / _LOCK_FILENAME
    if not lock_path.exists():
        return ProjectionLock()
    try:
        content = lock_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Lockfile {lock_path} is not valid utf-8: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read {lock_path}: {exc}") from exc
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {lock_path}: {exc}") from exc
    try:
        return ProjectionLock.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Malformed lockfile in {lock_path}: {exc}") from exc


def _record_lock(project_root: Path, target: str, entry: ProjectionEntry) -> None:
    """Set *target*'s entry in the lockfile and write it back.

    Creates ``.protean/`` if it does not exist and writes the lockfile with
    sorted keys and a trailing newline, the same house style as the manifest.
    """
    lock = load_lock(project_root).with_entry(target, entry)
    protean_dir = project_root / _LOCK_DIR
    protean_dir.mkdir(parents=True, exist_ok=True)
    lock_path = protean_dir / _LOCK_FILENAME
    # Write the lock atomically too, so a crash mid-write cannot corrupt it and
    # make every later projection fail to load it.
    _atomic_write(
        lock_path,
        json.dumps(lock.to_dict(), indent=2, sort_keys=True) + "\n",
    )
