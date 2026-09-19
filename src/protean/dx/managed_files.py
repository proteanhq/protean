"""An idempotent managed-file writer for ``protean dx``.

The writer generates a rendered artifact into a user's project and can re-write
it later without clobbering the user's own edits. It is the update-and-merge path
that :func:`~protean.scaffold.apply.apply_plan` defers: ``apply_plan`` is
create-only, so this writer composes with it for the create case and adds the
merge, diff, and conflict-detection the re-apply case needs.

Three merge modes cover the file shapes ``protean dx`` ships:

- **Managed block** (text). The framework block sits between two
  sentinel-comment markers, ``PROTEAN:BEGIN <block-id>`` and
  ``PROTEAN:END <block-id>``. A second apply replaces only the body between the
  markers and leaves every byte outside untouched. The caller passes the comment
  syntax (``<!-- -->`` for AGENTS.md, ``#`` for a config), so the writer stays
  format-agnostic.
- **Managed JSON keys**. The rendered dict's keys are the managed keys. A second
  apply sets those keys and preserves every other key on disk. An optional
  key-path scopes the merge to a nested object: with a path like
  ``("mcpServers",)`` the managed keys are set under ``mcpServers`` and every
  sibling there is preserved, so ``.mcp.json`` manages only its own
  ``mcpServers.protean`` entry and leaves the user's other servers alone. With no
  path the managed keys are the top-level ones.
- **Whole file** (text). The framework owns the entire file, with no user-owned
  region. The render is the whole content, so the managed slice is the whole file
  and a hand edit anywhere in it reads as a conflict. This is for a file whose
  format leaves no room for a marker line above its first byte, such as Cursor's
  ``.mdc`` rule file, whose YAML frontmatter must start at line 1.

A state file at ``.protean/dx-state.json`` records, per target path, the pack
version stamp and two hashes: the hash of the whole file the writer last wrote
and the hash of the managed slice it last wrote. The slice hash drives the diff
decision below (does the user's on-disk block still match what the writer wrote).
The whole-file hash is not consulted by that decision; it feeds only
``outside_modified``, the signal that the file drifted around an untouched block.
The diff decision:

- ``CREATE``: the target is absent.
- ``NO_CHANGE``: the on-disk slice equals the newly rendered slice and the
  version stamp matches. The no-op case; the state file is left untouched.
- ``UPDATE``: a safe write. Either the user left the block alone (on-disk slice
  equals what the state file last recorded) or the on-disk slice already equals
  the new content while the version stamp advanced.
- ``CONFLICT``: the on-disk slice differs from both the state file's last-written
  slice and the newly rendered slice, so the user edited inside the framework's
  territory. The writer writes nothing and surfaces the conflict.

Serialization follows the IR house style (see
:mod:`protean.scaffold.change_plan`): frozen dataclasses, an explicit
``to_dict``/``from_dict`` JSON dump with sorted keys and a trailing newline, and
a ``state_version`` marker that ``from_dict`` rejects loudly when it does not
understand it.

Line endings: the writer reads a target in text mode, so whatever the file uses
on disk arrives as ``\\n``, and every hash is taken over that utf-8-encoded,
LF-normalized text. A CRLF checkout of the same content therefore hashes the same
as an LF one and a benign platform newline difference never reads as a phantom
conflict. Writes go back out in whatever line ending the file already uses, so an
update never rewrites a file's line endings.

See ADR-0037 for the decision record behind the state file and the merge modes.

Design decisions for v1:

- **One pair per block id.** A managed-block target carries exactly one
  ``PROTEAN:BEGIN/END`` pair for the requested block id; other tools' blocks,
  with different ids, may sit in the same file and are left untouched. A missing,
  duplicated, or reversed marker for the requested id raises rather than silently
  overwriting the whole file.
- **Key-path JSON merge.** The managed keys are replaced whole at the merge path;
  every other key, nested structure and sibling under the path included, is
  preserved. With no path the merge is over the top-level keys; with a key-path it
  is scoped to the nested object at that path, which is how ``.mcp.json`` manages
  only ``mcpServers.protean`` and keeps the user's other servers.
- **Whole-file dx ownership.** A whole-file target has no user-owned region, so its
  managed slice is the whole file and ``slice_hash`` equals ``file_hash``. Any hand
  edit makes the on-disk content differ from both the render and the state, so the
  same slice-based decision reports it as a conflict. This is for a file whose format
  forbids a marker line above its first byte, such as Cursor's ``.mdc`` rule.

Usage::

    from pathlib import Path
    from protean.dx import ManagedBlock, apply_managed_file

    managed = ManagedBlock(
        target="AGENTS.md",
        version="0.1.0",
        block_id="protean",
        body="Framework-owned guidance.",
        comment_prefix="<!-- ",
        comment_suffix=" -->",
    )
    result = apply_managed_file(Path("my_project"), managed)
    assert result.status.value in {"create", "update", "no_change"}
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from protean.scaffold.apply import ApplyError, apply_plan
from protean.scaffold.change_plan import (
    OWNERSHIP_GENERATED,
    ChangePlan,
    CreateFileOperation,
)

__all__ = [
    "STATE_VERSION",
    "ApplyResult",
    "ApplyStatus",
    "FileStateEntry",
    "ManagedBlock",
    "ManagedFile",
    "ManagedFileConflict",
    "ManagedFileError",
    "ManagedFileState",
    "ManagedJsonKeys",
    "ManagedWholeFile",
    "MergeMode",
    "apply_managed_file",
    "diff_managed_file",
    "load_state",
]

# The version marker carried on every serialized state file. Bumped when the
# serialized shape changes incompatibly; a ``state_version`` the code does not
# understand is rejected loudly by :meth:`ManagedFileState.from_dict`.
STATE_VERSION = "1.0"

_STATE_DIR = ".protean"
_STATE_FILENAME = "dx-state.json"

# The fixed marker keywords. The caller wraps them in its own comment syntax.
_MARKER_BEGIN = "PROTEAN:BEGIN"
_MARKER_END = "PROTEAN:END"

# How much of a file to read when sniffing which line ending it uses.
_NEWLINE_SNIFF_BYTES = 8192


class ManagedFileError(Exception):
    """A managed-file failure the caller is meant to read and act on.

    Raised for a malformed managed-block target (a missing, duplicated, or
    reversed marker), a target that is not the JSON object a JSON-keys merge
    needs, or a corrupt state file. :class:`ManagedFileConflict` is the subclass
    for the specific case of a user edit inside the framework's territory.
    """


class ManagedFileConflict(ManagedFileError):
    """The user edited the managed content, so a re-apply is refused.

    Carries the *target* path and a *managed* description (the block id for a
    managed-block target, the managed key names for a managed-JSON-keys target)
    so a ``check`` or ``diff`` verb can report exactly what conflicts. The
    description names the managed content whichever merge mode raised, so it does
    not call a JSON-keys target a block.
    """

    def __init__(self, target: str, managed: str) -> None:
        self.target = target
        self.managed = managed
        super().__init__(
            f"Managed-file conflict at {target!r}: the managed content {managed!r} "
            "was edited by hand and now differs from the incoming content. Refusing "
            "to overwrite it; resolve the edit and re-run."
        )


class MergeMode(StrEnum):
    """The merge mode a managed file applies."""

    BLOCK = "block"
    """Replace the body between two sentinel-comment markers in a text file."""

    JSON_KEYS = "json_keys"
    """Set the managed top-level keys of a JSON object and preserve the rest."""

    WHOLE_FILE = "whole_file"
    """Own the entire text file: the render is the whole content, with no
    user-owned region. A hand edit anywhere in the file is a conflict."""


class ApplyStatus(StrEnum):
    """Outcome of a diff or apply."""

    CREATE = "create"
    """The target is absent; the writer would create it."""

    NO_CHANGE = "no_change"
    """On-disk slice matches the new slice and the version stamp matches."""

    UPDATE = "update"
    """A safe write: the block is untouched, or already equals the new content."""

    CONFLICT = "conflict"
    """The on-disk slice was edited to something neither the state file nor the
    render expects. The writer writes nothing."""


@dataclass(frozen=True)
class ManagedBlock:
    """A managed-block (text) apply request.

    ``comment_prefix`` and ``comment_suffix`` wrap the marker keyword: HTML passes
    ``"<!-- "`` and ``" -->"``, a ``#``-comment config passes ``"# "`` and ``""``.
    The begin marker line is therefore ``<prefix>PROTEAN:BEGIN <block_id><suffix>``.
    """

    target: str
    version: str
    block_id: str
    body: str
    comment_prefix: str
    comment_suffix: str = ""

    def __post_init__(self) -> None:
        if not self.block_id:
            raise ValueError("block_id must be a non-empty string")
        # The markers are single lines, so any part of them carrying a newline
        # would split the marker across lines and break the parse.
        for name, value in (
            ("block_id", self.block_id),
            ("comment_prefix", self.comment_prefix),
            ("comment_suffix", self.comment_suffix),
        ):
            if "\n" in value:
                raise ValueError(f"{name} must not contain a newline")
        # A body line identical to a marker line would frame a second, phantom
        # block and poison every later re-apply (the parse would count two
        # markers). Reject it at construction rather than write a self-poisoning
        # file.
        marker_lines = {self.begin_marker, self.end_marker}
        for line in self.body.split("\n"):
            if line in marker_lines:
                raise ValueError(
                    "body must not contain a line identical to a block marker "
                    f"({line!r}); it would frame a phantom block."
                )

    @property
    def mode(self) -> MergeMode:
        return MergeMode.BLOCK

    @property
    def begin_marker(self) -> str:
        """The full begin-marker line, comment syntax included."""
        return (
            f"{self.comment_prefix}{_MARKER_BEGIN} {self.block_id}{self.comment_suffix}"
        )

    @property
    def end_marker(self) -> str:
        """The full end-marker line, comment syntax included."""
        return (
            f"{self.comment_prefix}{_MARKER_END} {self.block_id}{self.comment_suffix}"
        )


@dataclass(frozen=True)
class ManagedJsonKeys:
    """A managed-JSON-keys apply request.

    ``data`` is the rendered dict. Its keys are the managed keys: a second apply
    sets them and preserves every other key on disk. ``data`` must be non-empty,
    since an empty managed set would manage nothing, and every key in it, nested
    ones included, must be a ``str``.

    ``path`` scopes the merge to a nested object. When ``path`` is empty (the
    default), the managed keys are the top-level keys and the merge is the shallow
    top-level one. When ``path`` names a key-path (say ``("mcpServers",)``), the
    managed keys are set under that path: the merge sets ``data``'s keys inside
    the object at ``path``, creates the path if it is absent, and preserves every
    sibling under the path and every other top-level key. This is how
    ``.mcp.json`` manages only its own ``mcpServers.protean`` entry and leaves the
    user's other servers alone. Each path segment must be a non-empty ``str`` with
    no newline.
    """

    target: str
    version: str
    data: Mapping[str, Any]
    path: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.data:
            raise ValueError("data must name at least one managed key")
        # A path segment is a JSON object key, so it must be a non-empty string.
        # A newline in a segment cannot name a real key and only muddies the error
        # messages that quote the path, so reject it at construction.
        for segment in self.path:
            if not isinstance(segment, str) or not segment:
                raise ValueError("each path segment must be a non-empty string")
            if "\n" in segment:
                raise ValueError("a path segment must not contain a newline")
        # The managed values are hashed and written as JSON, so they must be
        # JSON-serializable with string keys. Catch a non-serializable value
        # (a ``set``, ``bytes``) or a bad key here rather than raise a raw
        # ``TypeError`` deep in the diff path.
        _reject_non_string_keys(dict(self.data), "data")
        try:
            _canonical_json(dict(self.data))
        except TypeError as exc:
            raise ValueError(
                f"data must be JSON-serializable with string keys: {exc}"
            ) from exc

    @property
    def mode(self) -> MergeMode:
        return MergeMode.JSON_KEYS

    @property
    def managed_keys(self) -> tuple[str, ...]:
        """The managed keys under ``path``, in the render's order."""
        return tuple(self.data.keys())


@dataclass(frozen=True)
class ManagedWholeFile:
    """A whole-file (text) apply request: ``dx`` owns the entire file.

    Unlike a managed block, there is no user-owned region: the rendered ``body``
    is the whole file content. A hand edit anywhere in the file makes the on-disk
    content differ from both the render and the recorded state, which the diff
    reads as a conflict. This suits a file whose format has no place for a marker
    line above its first byte, such as Cursor's ``.mdc`` rule file, whose YAML
    frontmatter must start at line 1.

    The version stamp lives inside ``body`` (``render_agents_body`` leads with a
    version-stamped H1, and the Cursor renderer adds an explicit stamp line too),
    so the file on disk names the pack version that rendered it. Staleness does
    not depend on that: the state row carries the stamp as well, so a version bump
    reports ``UPDATE`` even when the rendered body is byte-identical.
    """

    target: str
    version: str
    body: str

    def __post_init__(self) -> None:
        # An empty body would create an empty file and manage nothing; a real
        # whole-file render always carries content.
        if not self.body:
            raise ValueError("body must be a non-empty string")

    @property
    def mode(self) -> MergeMode:
        return MergeMode.WHOLE_FILE


# The managed-file union. The writer dispatches on the concrete type.
ManagedFile = ManagedBlock | ManagedJsonKeys | ManagedWholeFile


@dataclass(frozen=True)
class FileStateEntry:
    """One target's row in the state file: the version stamp and the two hashes."""

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
    def from_dict(cls, data: Any, target: str) -> FileStateEntry:
        """Rebuild an entry, validating the shape and field types.

        A malformed entry (a non-object, a missing field, or a non-string value)
        fails loud rather than being coerced into a valid-looking entry.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"state entry for {target!r} must be an object, got {type(data).__name__}"
            )
        return cls(
            version=_require_str(data, "version", f"state entry {target!r}"),
            file_hash=_require_str(data, "file_hash", f"state entry {target!r}"),
            slice_hash=_require_str(data, "slice_hash", f"state entry {target!r}"),
        )


@dataclass(frozen=True)
class ManagedFileState:
    """The state file: a map from target path to its :class:`FileStateEntry`."""

    entries: dict[str, FileStateEntry] = field(default_factory=dict)

    def with_entry(self, target: str, entry: FileStateEntry) -> ManagedFileState:
        """Return a new state with *target*'s entry set to *entry*."""
        new_entries = dict(self.entries)
        new_entries[target] = entry
        return ManagedFileState(entries=new_entries)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict, carrying the ``state_version`` marker.

        Entries are emitted in sorted-key order so the persisted file is stable.
        """
        return {
            "state_version": STATE_VERSION,
            "entries": {
                path: self.entries[path].to_dict() for path in sorted(self.entries)
            },
        }

    @classmethod
    def from_dict(cls, data: Any) -> ManagedFileState:
        """Rebuild a state from its serialized dict.

        Raises :exc:`ValueError` on a non-object payload, on a ``state_version``
        the code does not understand, on a non-object ``entries`` map, or on a
        malformed entry. A corrupt or newer state file fails loud.
        """
        if not isinstance(data, dict):
            raise ValueError("A serialized ManagedFileState must be a mapping")
        version = data.get("state_version")
        if version != STATE_VERSION:
            raise ValueError(
                f"Unsupported state_version: {version!r}. "
                f"This build understands {STATE_VERSION!r}."
            )
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, dict):
            raise ValueError("ManagedFileState 'entries' must be an object")
        entries = {
            str(target): FileStateEntry.from_dict(entry, str(target))
            for target, entry in raw_entries.items()
        }
        return cls(entries=entries)


@dataclass(frozen=True)
class ApplyResult:
    """The outcome of a diff or apply. Mutates nothing on its own.

    ``content`` is the full file text the writer would write (``CREATE``) or did
    write (``UPDATE``); it is ``None`` for ``NO_CHANGE`` and ``CONFLICT``.
    ``file_hash`` is the hash of that content, ``None`` when ``content`` is.
    ``slice_hash`` is the hash of the newly rendered managed slice.
    ``outside_modified`` is ``True`` when the file drifted from the state file's
    recorded file hash while the managed slice stayed the same, so the drift is
    entirely outside the managed block. It is informational (a ``check`` or
    ``diff`` verb can report a user edit around the block) and does not by itself
    trigger a write.
    """

    target: str
    status: ApplyStatus
    version: str
    slice_hash: str
    content: str | None = None
    file_hash: str | None = None
    outside_modified: bool = False


def _require_str(data: dict[str, Any], key: str, context: str) -> str:
    """Return ``data[key]`` as a string, or raise a clear :exc:`ValueError`.

    Checks both presence and type, so a malformed state file fails loud instead
    of being coerced into a valid-looking string.
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

    *text* always comes from a text-mode read or the writer's own rendering, so
    its line endings are already LF whatever the file holds on disk. Fixed utf-8
    over that, so the hash is stable across platforms and a benign newline
    difference never reads as a phantom conflict.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    """Serialize *obj* to a canonical JSON string for hashing.

    Sorted keys and the tightest separators, so two equal structures always
    serialize to the same bytes whatever order the producer built them in.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _reject_non_string_keys(obj: Any, path: str) -> None:
    """Raise :exc:`ValueError` when *obj* holds a dict key that is not a ``str``.

    ``json.dumps`` accepts an ``int``, ``float``, ``bool``, or ``None`` key and
    silently coerces it to its string form, so it cannot enforce this on its own.
    A coerced managed key is worse than a lost type: the key on disk (``"1"``)
    never matches the key the caller passed (``1``), so the diff sees the managed
    value as missing and the target reads as conflicted on every re-apply.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise ValueError(
                    f"data must use string keys: {path} has key {key!r} "
                    f"of type {type(key).__name__}"
                )
            _reject_non_string_keys(value, f"{path}[{key!r}]")
    elif isinstance(obj, (list, tuple)):
        for index, item in enumerate(obj):
            _reject_non_string_keys(item, f"{path}[{index}]")


def _marker_line_positions(text: str, marker: str) -> list[int]:
    """Return the start offsets where *marker* occupies a whole line of *text*.

    The match is line-anchored: *marker* must start at the beginning of the file
    or just after a newline, and end at the end of the file or just before a
    newline. A plain substring (a marker keyword mentioned mid-line, or a shorter
    block id that is a prefix of a longer one) is not counted.
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

    Raises :exc:`ManagedFileError` when the marker is absent or appears more than
    once, so a malformed managed-block target is refused rather than silently
    overwritten. Matching is line-anchored (see :func:`_marker_line_positions`),
    so a shorter block id that is a prefix of a longer one does not mismatch.
    The marker carries the requested block id, so another tool's block with a
    different id in the same file does not count as a second occurrence.
    """
    positions = _marker_line_positions(text, marker)
    if len(positions) == 0:
        raise ManagedFileError(
            f"Managed-block target {target!r} is missing its marker {marker!r}. "
            "Refusing to overwrite the file."
        )
    if len(positions) > 1:
        raise ManagedFileError(
            f"Managed-block target {target!r} carries {len(positions)} copies of "
            f"the marker {marker!r}; exactly one is supported. Refusing to overwrite "
            "the file."
        )
    return positions[0]


def _block_bounds(text: str, block: ManagedBlock) -> tuple[int, int]:
    """Return ``(after_begin, end_start)`` string indices of the managed body.

    ``after_begin`` is the index just past the begin-marker line; ``end_start``
    is the index where the end-marker line starts. Both index the decoded text,
    not its utf-8 bytes. Raises
    :exc:`ManagedFileError` when either marker is malformed or the end marker
    precedes the begin marker.
    """
    begin_pos = _find_unique_marker(text, block.begin_marker, block.target)
    end_pos = _find_unique_marker(text, block.end_marker, block.target)
    if end_pos < begin_pos:
        raise ManagedFileError(
            f"Managed-block target {block.target!r} has its end marker before "
            "its begin marker. Refusing to overwrite the file."
        )
    return begin_pos + len(block.begin_marker), end_pos


def _extract_block_body(text: str, block: ManagedBlock) -> str:
    """Return the current body between the markers, minus the framing newlines.

    The writer writes a block as ``<begin>\\n<body>\\n<end>``, so the raw text
    between the markers carries one leading and one trailing newline. Stripping at
    most one of each recovers the body the writer wrote, and reconstructing it the
    same way round-trips.
    """
    after_begin, end_start = _block_bounds(text, block)
    raw = text[after_begin:end_start]
    if raw.startswith("\n"):
        raw = raw[1:]
    if raw.endswith("\n"):
        raw = raw[:-1]
    return raw


def _merge_block(text: str, block: ManagedBlock) -> str:
    """Replace the managed body in *text* with the block's new body.

    Everything outside the markers, the marker lines included, is preserved
    byte-for-byte.
    """
    after_begin, end_start = _block_bounds(text, block)
    before = text[:after_begin]
    after = text[end_start:]
    return f"{before}\n{block.body}\n{after}"


def _create_block(block: ManagedBlock) -> str:
    """Render a fresh managed-block file: just the block, plus a trailing newline."""
    return f"{block.begin_marker}\n{block.body}\n{block.end_marker}\n"


def _parse_json_object(text: str, target: str) -> dict[str, Any]:
    """Parse *text* as a JSON object, or raise :exc:`ManagedFileError`.

    A JSON-keys merge needs a top-level object; a non-object or invalid JSON
    target fails loud rather than being silently overwritten.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManagedFileError(
            f"Managed-JSON-keys target {target!r} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ManagedFileError(
            f"Managed-JSON-keys target {target!r} must be a JSON object, "
            f"got {type(data).__name__}."
        )
    return data


def _json_slice_input(source: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    """Canonical hash-input for the managed *keys* of *source*, presence included.

    Each key contributes ``[key, present, value]``. Carrying ``present`` keeps a
    key that is absent distinct from one set to ``null``: ``dict.get`` answers
    ``None`` for both, so hashing the values alone would read "add a key whose
    value is ``null``" as a no-op and miss a user deleting a managed key. Keys are
    sorted so the disk and new slices compare regardless of their order.
    """
    return _canonical_json(
        [[key, key in source, source.get(key)] for key in sorted(keys)]
    )


def _walk_to_object(
    disk: dict[str, Any], path: tuple[str, ...], target: str
) -> dict[str, Any] | None:
    """Return the object at *path* in *disk*, or ``None`` when the path is absent.

    Walks *path* segment by segment. A segment that is not present returns
    ``None`` (the managed key-path has no footprint on disk yet). A segment that
    is present but is not a JSON object raises :exc:`ManagedFileError`, so a merge
    never clobbers a user's non-object value (``mcpServers`` set to a string, an
    array, or ``null``) at the path.
    """
    node: dict[str, Any] = disk
    for depth, segment in enumerate(path):
        if segment not in node:
            return None
        child = node[segment]
        if not isinstance(child, dict):
            walked = ".".join(path[: depth + 1])
            raise ManagedFileError(
                f"Managed-JSON-keys target {target!r} has {walked!r} set to a "
                f"{type(child).__name__}, but the managed key-path needs it to be a "
                "JSON object. Refusing to overwrite it."
            )
        node = child
    return node


def _json_disk_slice(disk: dict[str, Any], managed: ManagedJsonKeys) -> str:
    """Canonical hash-input for the managed keys' current on-disk values at the path.

    Walks ``managed.path`` first, then hashes the managed keys of the object
    found there. An absent path contributes an empty object, so every managed key
    reads as absent.
    """
    sub = _walk_to_object(disk, managed.path, managed.target)
    source: Mapping[str, Any] = sub if sub is not None else {}
    return _json_slice_input(source, managed.managed_keys)


def _json_disk_keys_absent(disk: dict[str, Any], managed: ManagedJsonKeys) -> bool:
    """Return ``True`` when every managed key is absent at ``managed.path``.

    The framework then has no footprint at the key-path, so a first install is a
    safe add rather than a conflict. A present-but-hand-edited managed key makes
    this ``False``, keeping that case a conflict.
    """
    sub = _walk_to_object(disk, managed.path, managed.target)
    source: Mapping[str, Any] = sub if sub is not None else {}
    return all(key not in source for key in managed.managed_keys)


def _json_new_slice(managed: ManagedJsonKeys) -> str:
    """Canonical hash-input for the newly rendered managed values."""
    return _json_slice_input(managed.data, managed.managed_keys)


def _merge_json(disk: dict[str, Any], managed: ManagedJsonKeys) -> str:
    """Merge the managed keys into *disk* at ``managed.path`` and render the file.

    Deep-copies *disk* so the parsed disk dict is left unmutated, walks down
    ``managed.path`` (creating an empty object for a missing segment), sets the
    managed keys there, and preserves every sibling and every other key. With an
    empty path this is the shallow top-level merge. A path segment that exists but
    is not a JSON object raises :exc:`ManagedFileError`. Rendered with two-space
    indent, sorted keys, and a trailing newline.
    """
    merged = copy.deepcopy(disk)
    node = merged
    for depth, segment in enumerate(managed.path):
        if segment not in node:
            node[segment] = {}
        elif not isinstance(node[segment], dict):
            walked = ".".join(managed.path[: depth + 1])
            raise ManagedFileError(
                f"Managed-JSON-keys target {managed.target!r} has {walked!r} set to "
                f"a {type(node[segment]).__name__}, but the managed key-path needs it "
                "to be a JSON object. Refusing to overwrite it."
            )
        node = node[segment]
    node.update(managed.data)
    return json.dumps(merged, indent=2, sort_keys=True) + "\n"


def _create_json(managed: ManagedJsonKeys) -> str:
    """Render a fresh managed-JSON-keys file: the managed keys wrapped in the path.

    With an empty path this is the managed keys alone; with a path the keys are
    nested under it (``{"mcpServers": {"protean": ...}}``).
    """
    obj: dict[str, Any] = dict(managed.data)
    for segment in reversed(managed.path):
        obj = {segment: obj}
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def _decide(
    disk_slice_hash: str,
    state_slice_hash: str | None,
    new_slice_hash: str,
    version_match: bool,
    *,
    disk_keys_absent: bool = False,
) -> ApplyStatus:
    """Classify a re-apply over an existing target.

    The conflict predicate is ``disk != state and disk != new`` (a state hash of
    ``None``, meaning no recorded entry, counts as "disk != state"). Everything
    that is not that predicate and not the pure no-op is a safe write:

    - ``NO_CHANGE``: the slice already equals the new slice and the version stamp
      matches. Nothing to do.
    - ``UPDATE``: the block is untouched (``disk == state``), or the on-disk slice
      already equals the new content while the version advanced. Both are safe to
      write; the second rewrites identical bytes and advances the state file.
    - ``CONFLICT``: neither. The user edited the slice to something the writer did
      not write and the render does not want.

    ``disk_keys_absent`` is the managed-JSON-keys signal that every managed key is
    absent at the merge path and there is no state entry: the framework has no
    footprint there, so a first install onto a pre-existing file is a safe add
    that keeps the user's other keys, not a conflict. It stays ``False`` for the
    block mode and for a target with a state entry (where an absent managed key is
    the user deleting one the writer wrote, which is a conflict).
    """
    if disk_slice_hash == new_slice_hash and version_match:
        return ApplyStatus.NO_CHANGE
    if state_slice_hash is not None and disk_slice_hash == state_slice_hash:
        return ApplyStatus.UPDATE
    if disk_slice_hash == new_slice_hash:
        return ApplyStatus.UPDATE
    if disk_keys_absent and state_slice_hash is None:
        return ApplyStatus.UPDATE
    return ApplyStatus.CONFLICT


def _resolve_target(root: Path, target: str) -> Path:
    """Return the path *target* names under *root*, refusing anything outside it.

    A target must be a non-empty relative path that stays under the project root
    once resolved. ``root / "/etc/passwd"`` discards the root, and a ``..``
    segment or a symlinked parent directory climbs out of it, so without this
    check an update would read and write anywhere on the filesystem.
    :func:`~protean.scaffold.apply.apply_plan` runs the same checks on the CREATE
    path; this one covers UPDATE too, and it runs before anything is read.

    The returned path is the unresolved ``root / target``, so the symlink check in
    :func:`diff_managed_file` still sees a final-component symlink as the symlink
    it is.
    """
    if not target:
        raise ManagedFileError("Managed-file target must be a non-empty path.")
    candidate = Path(target)
    # ``drive`` also covers the Windows drive-relative form (``C:file.json``),
    # which is not absolute but is not root-relative either.
    if candidate.is_absolute() or candidate.drive:
        raise ManagedFileError(
            f"Managed file refuses an absolute target: {target!r}. A target must be "
            "relative to the project root."
        )
    if not (root / candidate).resolve().is_relative_to(root.resolve()):
        raise ManagedFileError(
            f"Managed file refuses a target outside the project root: {target!r}. "
            "A target must stay under the project."
        )
    return root / candidate


def diff_managed_file(
    project_root: Path | str, managed_file: ManagedFile
) -> ApplyResult:
    """Compute what applying *managed_file* would do, without touching disk.

    Recomputes the on-disk state, compares it against the state file and the newly
    rendered artifact, and returns an :class:`ApplyResult` carrying the status
    and, for a write, the merged content and its hashes. Mirrors
    :func:`~protean.scaffold.manifest.check_manifest_drift`: derive and compare,
    mutate nothing.

    Raises :exc:`ManagedFileError` when the target escapes the project root, when
    it is a symlink, when the state directory or state file is a symlink, when the
    target cannot be read, when a managed-block target has a malformed marker,
    when a managed-JSON-keys target is not a JSON object or a key-path segment on
    disk is not a JSON object, or when the state file is corrupt.
    """
    root = Path(project_root)
    target_path = _resolve_target(root, managed_file.target)
    # ``load_state`` keeps its own ``ValueError`` contract for direct callers; the
    # managed-file APIs document a corrupt state file as ``ManagedFileError``, so
    # translate at this boundary.
    try:
        state = load_state(root)
    except ValueError as exc:
        raise ManagedFileError(str(exc)) from exc
    entry = state.entries.get(managed_file.target)

    if isinstance(managed_file, ManagedBlock):
        new_slice = managed_file.body
        create_content = _create_block(managed_file)
    elif isinstance(managed_file, ManagedWholeFile):
        # The whole file is the managed slice, so the slice hash equals the file
        # hash and any hand edit anywhere reads as a changed slice.
        new_slice = managed_file.body
        create_content = managed_file.body
    else:
        new_slice = _json_new_slice(managed_file)
        create_content = _create_json(managed_file)
    new_slice_hash = _hash_text(new_slice)

    if target_path.is_symlink():
        raise ManagedFileError(
            f"Target {managed_file.target!r} is a symlink. Refusing to write onto "
            "it: an update would replace the link with a regular file and leave "
            "the link's target behind."
        )

    if not target_path.exists():
        return ApplyResult(
            target=managed_file.target,
            status=ApplyStatus.CREATE,
            version=managed_file.version,
            slice_hash=new_slice_hash,
            content=create_content,
            file_hash=_hash_text(create_content),
            outside_modified=False,
        )

    try:
        disk_content = target_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ManagedFileError(
            f"Target {managed_file.target!r} is not valid utf-8: {exc}. "
            "Refusing to overwrite it."
        ) from exc
    except OSError as exc:
        # A directory at the target, a permission error, or any other read
        # failure. Surface the module's error type, not a raw OSError.
        raise ManagedFileError(
            f"Could not read target {managed_file.target!r}: {exc}. "
            "Refusing to overwrite it."
        ) from exc
    disk_keys_absent = False
    if isinstance(managed_file, ManagedBlock):
        disk_slice = _extract_block_body(disk_content, managed_file)
        merged = _merge_block(disk_content, managed_file)
    elif isinstance(managed_file, ManagedWholeFile):
        # The whole disk content is the slice; the merge is the render, verbatim.
        disk_slice = disk_content
        merged = managed_file.body
    else:
        disk = _parse_json_object(disk_content, managed_file.target)
        disk_slice = _json_disk_slice(disk, managed_file)
        disk_keys_absent = _json_disk_keys_absent(disk, managed_file)
        merged = _merge_json(disk, managed_file)

    disk_slice_hash = _hash_text(disk_slice)
    version_match = entry is not None and entry.version == managed_file.version
    state_slice_hash = entry.slice_hash if entry is not None else None
    # The file drifted from what the writer wrote, but the managed slice is
    # untouched, so the drift is entirely outside the managed block.
    outside_modified = (
        entry is not None
        and entry.file_hash != _hash_text(disk_content)
        and disk_slice_hash == entry.slice_hash
    )

    status = _decide(
        disk_slice_hash,
        state_slice_hash,
        new_slice_hash,
        version_match,
        disk_keys_absent=disk_keys_absent,
    )
    writes = status is ApplyStatus.UPDATE
    return ApplyResult(
        target=managed_file.target,
        status=status,
        version=managed_file.version,
        slice_hash=new_slice_hash,
        content=merged if writes else None,
        file_hash=_hash_text(merged) if writes else None,
        outside_modified=outside_modified,
    )


def apply_managed_file(
    project_root: Path | str, managed_file: ManagedFile
) -> ApplyResult:
    """Apply *managed_file* under *project_root*, idempotently.

    Runs :func:`diff_managed_file` first, then acts on the status:

    - ``CONFLICT``: writes nothing and raises :exc:`ManagedFileConflict`.
    - ``NO_CHANGE``: does nothing and leaves the state file untouched.
    - ``CREATE``: delegates to :func:`~protean.scaffold.apply.apply_plan`, reusing
      its pre-flight and rollback, then records the state entry.
    - ``UPDATE``: writes the merged file in place (atomically, via a temp file and
      an ``os.replace``), then records the state entry. The file is written before
      the state file, so a failed write leaves the state on the prior stamp.

    Returns the :class:`ApplyResult` from the diff. Raises
    :exc:`ManagedFileConflict` on a conflict, and :exc:`ManagedFileError` for the
    diff-time failures :func:`diff_managed_file` lists and for a write that fails
    (the create path's ``ApplyError`` and any write-time ``OSError`` are surfaced
    as :exc:`ManagedFileError`).
    """
    root = Path(project_root)
    result = diff_managed_file(root, managed_file)

    if result.status is ApplyStatus.CONFLICT:
        if isinstance(managed_file, ManagedBlock):
            managed = managed_file.block_id
        elif isinstance(managed_file, ManagedWholeFile):
            managed = "the whole file"
        else:
            managed = ", ".join(managed_file.managed_keys)
        raise ManagedFileConflict(target=managed_file.target, managed=managed)

    if result.status is ApplyStatus.NO_CHANGE:
        return result

    # CREATE and UPDATE both carry the content to write; narrow for the type
    # checker (CONFLICT and NO_CHANGE, the None-content cases, already returned).
    assert result.content is not None and result.file_hash is not None

    # The create path raises ``ApplyError`` and every write path can raise
    # ``OSError``; surface them as the module's own error type so a caller of the
    # public API handles one exception family. A ``ManagedFileError`` already
    # raised inside (a symlinked target or state path) is not an ``OSError``, so
    # it passes through unwrapped.
    try:
        if result.status is ApplyStatus.CREATE:
            plan = ChangePlan(
                operations=(
                    CreateFileOperation(
                        path=managed_file.target,
                        content=result.content,
                        ownership=OWNERSHIP_GENERATED,
                    ),
                )
            )
            apply_plan(str(root), plan)
        else:  # UPDATE
            _atomic_write(_resolve_target(root, managed_file.target), result.content)

        _record_state(
            root,
            managed_file.target,
            FileStateEntry(
                version=result.version,
                file_hash=result.file_hash,
                slice_hash=result.slice_hash,
            ),
        )
    except (ApplyError, OSError) as exc:
        raise ManagedFileError(
            f"Could not write managed file for {managed_file.target!r}: {exc}."
        ) from exc
    return result


def _detect_newline(path: Path) -> str:
    """Return the newline sequence *path* already uses, ``"\\n"`` when it has none.

    Only the first line ending is inspected, which is enough for the consistent
    files the writer manages. A missing or unreadable file answers ``"\\n"``:
    the writer's own rendering is LF.
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


def _umask_mode(base: int) -> int:
    """Return *base* masked by the process umask: the mode a normal write would get.

    :func:`tempfile.mkstemp` always creates at 0600, narrower than the rest of the
    scaffold, which writes through umask-respecting ``write_text``. Reading the
    umask means setting it and putting it straight back; this runs on the
    single-threaded CLI scaffold path, so the brief window is safe.
    """
    current = os.umask(0)
    os.umask(current)
    return base & ~current


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically: a sibling temp file, then a rename.

    ``os.replace`` is atomic within a filesystem, so a failed write leaves the
    prior file intact rather than a half-written one. The temp sibling is created
    by :func:`tempfile.mkstemp`, so it gets a unique name and is created
    exclusively. A fixed name would overwrite, then delete, any file a user or
    another tool happened to leave at that path.

    *content* carries LF line endings; they are written back in whatever style the
    file already uses, so an update never rewrites a file's line endings. A default
    text write would translate them to the platform's own ending instead, which on
    Windows flips every line in the file, the ones outside the managed block too.
    """
    newline = _detect_newline(path)
    mode = path.stat().st_mode if path.exists() else None
    handle_fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".dx-tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8", newline=newline) as handle:
            handle.write(content)
        # ``mkstemp`` creates at 0600. Carry the target's own permissions over an
        # update; for a new file, match a umask-respecting write so a managed-file
        # write neither silently narrows an existing file nor forces a new state
        # file wider than the user's umask would allow.
        os.chmod(tmp, stat.S_IMODE(mode) if mode is not None else _umask_mode(0o666))
        os.replace(tmp, path)
    finally:
        # A failed write (or a failed replace) must not leave a stale temp
        # sibling behind. The successful replace already consumed ``tmp``.
        tmp.unlink(missing_ok=True)


def _resolve_state_path(project_root: Path) -> Path:
    """Return the state file path, refusing a symlinked state dir or state file.

    A ``.protean`` directory or a ``dx-state.json`` file that is a symlink would
    let a read or write follow the link outside the project tree, the same escape
    the target path is already guarded against. Refuse it before the path is
    treated as absent, read, or written.
    """
    state_dir = project_root / _STATE_DIR
    if state_dir.is_symlink():
        raise ManagedFileError(
            f"State directory {state_dir} is a symlink; refusing to follow it "
            "outside the project tree."
        )
    state_path = state_dir / _STATE_FILENAME
    if state_path.is_symlink():
        raise ManagedFileError(
            f"State file {state_path} is a symlink; refusing to follow it outside "
            "the project tree."
        )
    return state_path


def load_state(project_root: Path | str) -> ManagedFileState:
    """Load the state file from ``<project_root>/.protean/dx-state.json``.

    Returns an empty :class:`ManagedFileState` when the file is absent, which is
    how a first apply reads. Raises :exc:`ValueError` when the file exists but
    cannot be read, is not valid JSON, or does not carry the state shape (an
    unknown ``state_version`` included), and :exc:`ManagedFileError` when the
    state directory or state file is a symlink.
    """
    state_path = _resolve_state_path(Path(project_root))
    if not state_path.exists():
        return ManagedFileState()
    try:
        content = state_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"State file {state_path} is not valid utf-8: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"Could not read {state_path}: {exc}") from exc
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {state_path}: {exc}") from exc
    try:
        return ManagedFileState.from_dict(data)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Malformed state file in {state_path}: {exc}") from exc


def _record_state(project_root: Path, target: str, entry: FileStateEntry) -> None:
    """Set *target*'s entry in the state file and write it back.

    Creates ``.protean/`` if it does not exist and writes the state file with
    sorted keys and a trailing newline, the same house style as the manifest.
    """
    state = load_state(project_root).with_entry(target, entry)
    # Re-check the state path is not a symlink before creating the dir or writing,
    # so the write cannot follow a link outside the project tree either.
    state_path = _resolve_state_path(project_root)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    # Write the state file atomically too, so a crash mid-write cannot corrupt it
    # and make every later apply fail to load it.
    _atomic_write(
        state_path,
        json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n",
    )
