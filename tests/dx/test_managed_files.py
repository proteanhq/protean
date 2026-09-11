"""Behavioral tests for the idempotent managed-file writer."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from protean.dx.managed_files import (
    STATE_VERSION,
    ApplyStatus,
    FileStateEntry,
    ManagedBlock,
    ManagedFileConflict,
    ManagedFileError,
    ManagedFileState,
    ManagedJsonKeys,
    MergeMode,
    apply_managed_file,
    diff_managed_file,
    load_state,
)

# The managed-file writer is pure filesystem behavior and never touches a domain,
# so skip the autouse ``test_domain`` fixture's per-test domain setup.
pytestmark = pytest.mark.no_test_domain

# --- helpers ---------------------------------------------------------------


def block(target: str, version: str, body: str) -> ManagedBlock:
    """An HTML-comment managed block for AGENTS.md-style files."""
    return ManagedBlock(
        target=target,
        version=version,
        block_id="protean",
        body=body,
        comment_prefix="<!-- ",
        comment_suffix=" -->",
    )


def json_keys(target: str, version: str, data: dict) -> ManagedJsonKeys:
    return ManagedJsonKeys(target=target, version=version, data=data)


def state_path(root: Path) -> Path:
    return root / ".protean" / "dx-state.json"


# --- managed block ---------------------------------------------------------


def test_create_writes_block_and_state_then_rerun_is_no_op(tmp_path: Path) -> None:
    """Create path: apply into an absent target, then a re-run is NO_CHANGE."""
    result = apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1 block"))

    assert result.status is ApplyStatus.CREATE
    target = tmp_path / "AGENTS.md"
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert content == (
        "<!-- PROTEAN:BEGIN protean -->\nv1 block\n<!-- PROTEAN:END protean -->\n"
    )
    assert content.endswith("\n")  # trailing newline, byte-for-byte hashing input
    assert state_path(tmp_path).exists()

    rerun = apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1 block"))
    assert rerun.status is ApplyStatus.NO_CHANGE
    assert target.read_text(encoding="utf-8") == content


def test_update_preserves_user_text_outside_block(tmp_path: Path) -> None:
    """A second apply updates only the managed body; user text around it survives."""
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1 block"))
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "USER TOP\n" + target.read_text(encoding="utf-8") + "USER BOTTOM\n",
        encoding="utf-8",
    )

    result = apply_managed_file(tmp_path, block("AGENTS.md", "2", "v2 block"))

    assert result.status is ApplyStatus.UPDATE
    updated = target.read_text(encoding="utf-8")
    assert updated == (
        "USER TOP\n"
        "<!-- PROTEAN:BEGIN protean -->\nv2 block\n<!-- PROTEAN:END protean -->\n"
        "USER BOTTOM\n"
    )


def test_edit_outside_block_still_updates_and_is_reported(tmp_path: Path) -> None:
    """An edit outside the markers is safe: the block updates and the edit lives."""
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1 block"))
    target = tmp_path / "AGENTS.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "EXTRA USER LINE\n", encoding="utf-8"
    )

    result = apply_managed_file(tmp_path, block("AGENTS.md", "2", "v2 block"))

    assert result.status is ApplyStatus.UPDATE
    assert result.outside_modified is True
    updated = target.read_text(encoding="utf-8")
    assert "v2 block" in updated
    assert "v1 block" not in updated
    assert updated.endswith("EXTRA USER LINE\n")


def test_conflict_on_user_edit_inside_block_writes_nothing(tmp_path: Path) -> None:
    """A user edit inside the markers is a CONFLICT: diff reports it, apply refuses."""
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1 block"))
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "<!-- PROTEAN:BEGIN protean -->\nhacked by user\n"
        "<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )
    before = target.read_text(encoding="utf-8")
    state_before = state_path(tmp_path).read_text(encoding="utf-8")

    proj = block("AGENTS.md", "2", "v2 block")
    diff = diff_managed_file(tmp_path, proj)
    assert diff.status is ApplyStatus.CONFLICT
    assert diff.content is None
    # The edit is inside the block, so the drift is not "outside".
    assert diff.outside_modified is False

    with pytest.raises(ManagedFileConflict) as excinfo:
        apply_managed_file(tmp_path, proj)
    assert excinfo.value.target == "AGENTS.md"
    assert "protean" in excinfo.value.block

    assert target.read_text(encoding="utf-8") == before  # nothing written
    assert state_path(tmp_path).read_text(encoding="utf-8") == state_before


def test_user_edit_equal_to_new_content_is_not_a_conflict(tmp_path: Path) -> None:
    """If the user's edit happens to equal the incoming content, it is no conflict.

    The block body already matches the new render, so there is no data to lose.
    The version advanced, so the writer records a safe UPDATE (an identical write
    that advances the state file) rather than blocking.
    """
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "A"))
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "<!-- PROTEAN:BEGIN protean -->\nB\n<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )

    result = apply_managed_file(tmp_path, block("AGENTS.md", "2", "B"))

    assert result.status is ApplyStatus.UPDATE
    assert (
        target.read_text(encoding="utf-8")
        == "<!-- PROTEAN:BEGIN protean -->\nB\n<!-- PROTEAN:END protean -->\n"
    )
    # The state file advanced to the new version, so a further re-run is a no-op.
    assert apply_managed_file(tmp_path, block("AGENTS.md", "2", "B")).status is (
        ApplyStatus.NO_CHANGE
    )


def test_empty_body_round_trips_and_reruns_as_a_no_op(tmp_path: Path) -> None:
    """An empty managed body writes an empty block and reads back as empty."""
    managed = block("AGENTS.md", "1", "")
    assert apply_managed_file(tmp_path, managed).status is ApplyStatus.CREATE
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == (
        "<!-- PROTEAN:BEGIN protean -->\n\n<!-- PROTEAN:END protean -->\n"
    )
    assert apply_managed_file(tmp_path, managed).status is ApplyStatus.NO_CHANGE


def test_hand_written_adjacent_markers_read_as_an_empty_block(tmp_path: Path) -> None:
    """Markers a user wrote on adjacent lines parse as an empty body, not a broken one."""
    (tmp_path / "AGENTS.md").write_text(
        "<!-- PROTEAN:BEGIN protean -->\n<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )
    result = diff_managed_file(tmp_path, block("AGENTS.md", "1", "Framework guidance."))
    # An empty on-disk block matches neither the state file (there is none) nor the
    # new body, so it is a conflict rather than a silent overwrite.
    assert result.status is ApplyStatus.CONFLICT


def test_missing_end_marker_raises_and_does_not_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    original = "<!-- PROTEAN:BEGIN protean -->\nbody with no end\n"
    target.write_text(original, encoding="utf-8")

    with pytest.raises(ManagedFileError, match="missing its marker"):
        apply_managed_file(tmp_path, block("AGENTS.md", "1", "new"))
    assert target.read_text(encoding="utf-8") == original


def test_no_markers_raises(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_text("just some prose, no markers\n", encoding="utf-8")

    with pytest.raises(ManagedFileError, match="missing its marker"):
        diff_managed_file(tmp_path, block("AGENTS.md", "1", "new"))


def test_duplicate_begin_markers_raise(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "<!-- PROTEAN:BEGIN protean -->\na\n<!-- PROTEAN:END protean -->\n"
        "<!-- PROTEAN:BEGIN protean -->\nb\n<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )
    with pytest.raises(ManagedFileError, match="copies of the marker"):
        diff_managed_file(tmp_path, block("AGENTS.md", "1", "new"))


def test_reversed_markers_raise(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "<!-- PROTEAN:END protean -->\nbody\n<!-- PROTEAN:BEGIN protean -->\n",
        encoding="utf-8",
    )
    with pytest.raises(ManagedFileError, match="end marker before"):
        diff_managed_file(tmp_path, block("AGENTS.md", "1", "new"))


def test_prefix_block_id_does_not_false_match(tmp_path: Path) -> None:
    """A block id that is a prefix of another does not match the longer one.

    With an empty comment suffix, ``protean`` is a plain substring of
    ``protean-extra``. Line-anchored marker matching must not treat the
    ``protean-extra`` block as the ``protean`` block.
    """
    target = tmp_path / "config.ini"
    target.write_text(
        "# PROTEAN:BEGIN protean-extra\nother tool block\n# PROTEAN:END protean-extra\n",
        encoding="utf-8",
    )
    proj = ManagedBlock(
        target="config.ini",
        version="1",
        block_id="protean",
        body="framework block",
        comment_prefix="# ",
    )
    with pytest.raises(ManagedFileError, match="missing its marker"):
        diff_managed_file(tmp_path, proj)
    # The other tool's block is left untouched.
    assert target.read_text(encoding="utf-8") == (
        "# PROTEAN:BEGIN protean-extra\nother tool block\n# PROTEAN:END protean-extra\n"
    )


def test_prefix_block_id_updates_only_its_own_block(tmp_path: Path) -> None:
    """Two blocks whose ids share a prefix are told apart; only the named one moves."""
    v1 = ManagedBlock(
        target="config.ini",
        version="1",
        block_id="protean",
        body="framework v1",
        comment_prefix="# ",
    )
    apply_managed_file(tmp_path, v1)  # establishes the state for the protean block
    target = tmp_path / "config.ini"
    # A second tool appends its own block whose id starts with "protean".
    target.write_text(
        target.read_text(encoding="utf-8")
        + "# PROTEAN:BEGIN protean-extra\nother tool block\n"
        "# PROTEAN:END protean-extra\n",
        encoding="utf-8",
    )

    v2 = ManagedBlock(
        target="config.ini",
        version="2",
        block_id="protean",
        body="framework v2",
        comment_prefix="# ",
    )
    merged = diff_managed_file(tmp_path, v2)
    assert merged.status is ApplyStatus.UPDATE
    assert merged.content == (
        "# PROTEAN:BEGIN protean\nframework v2\n# PROTEAN:END protean\n"
        "# PROTEAN:BEGIN protean-extra\nother tool block\n# PROTEAN:END protean-extra\n"
    )


def test_body_containing_a_marker_line_is_rejected() -> None:
    """A body line identical to a marker would frame a phantom block: reject it."""
    with pytest.raises(ValueError, match="identical to a block marker"):
        ManagedBlock(
            target="config.ini",
            version="1",
            block_id="protean",
            body="# PROTEAN:END protean",
            comment_prefix="# ",
        )


def test_non_utf8_target_raises_managed_file_error(tmp_path: Path) -> None:
    """A non-utf-8 managed-block target fails as a ManagedFileError, not a raw decode."""
    target = tmp_path / "AGENTS.md"
    target.write_bytes(b"\xff\xfe not utf-8 at all")
    with pytest.raises(ManagedFileError, match="not valid utf-8"):
        diff_managed_file(tmp_path, block("AGENTS.md", "1", "new"))


def test_unreadable_target_surfaces_as_managed_file_error(tmp_path: Path) -> None:
    """A directory (or other OS-level read failure) at the target is a ManagedFileError.

    ``Path.read_text`` on a directory raises ``IsADirectoryError``; the public API
    surfaces the module's own error type, not a raw ``OSError``.
    """
    (tmp_path / "AGENTS.md").mkdir()
    proj = block("AGENTS.md", "1", "framework block")

    for call in (diff_managed_file, apply_managed_file):
        with pytest.raises(ManagedFileError, match="Could not read"):
            call(tmp_path, proj)


def test_create_write_failure_surfaces_as_managed_file_error(tmp_path: Path) -> None:
    """A failing create surfaces as ManagedFileError, not the scaffold's ApplyError.

    ``apply_plan`` raises ``ApplyError`` when the project root is not a directory;
    ``apply_managed_file`` wraps it so callers handle one exception family.
    """
    missing_root = tmp_path / "does-not-exist"
    with pytest.raises(ManagedFileError, match="Could not write"):
        apply_managed_file(missing_root, block("AGENTS.md", "1", "framework block"))


def test_hash_mode_uses_comment_syntax_config(tmp_path: Path) -> None:
    """A ``#``-comment config target applies and re-applies idempotently."""
    proj = ManagedBlock(
        target="config.ini",
        version="1",
        block_id="protean",
        body="key = value",
        comment_prefix="# ",
    )
    result = apply_managed_file(tmp_path, proj)
    assert result.status is ApplyStatus.CREATE
    assert (tmp_path / "config.ini").read_text(encoding="utf-8") == (
        "# PROTEAN:BEGIN protean\nkey = value\n# PROTEAN:END protean\n"
    )


def test_version_bump_with_identical_body_updates_and_advances_state(
    tmp_path: Path,
) -> None:
    """A re-install (version bumped, same body, untouched file) is a safe UPDATE.

    The block is untouched, so the write is safe; the state file must advance to
    the new version so the next identical re-run reads as a no-op.
    """
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "same body"))

    result = apply_managed_file(tmp_path, block("AGENTS.md", "2", "same body"))
    assert result.status is ApplyStatus.UPDATE

    rerun = apply_managed_file(tmp_path, block("AGENTS.md", "2", "same body"))
    assert rerun.status is ApplyStatus.NO_CHANGE


def test_no_change_leaves_the_state_file_untouched(tmp_path: Path) -> None:
    """A NO_CHANGE re-run must not rewrite the state file."""
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "block"))
    state_before = state_path(tmp_path).read_text(encoding="utf-8")

    result = apply_managed_file(tmp_path, block("AGENTS.md", "1", "block"))
    assert result.status is ApplyStatus.NO_CHANGE
    assert state_path(tmp_path).read_text(encoding="utf-8") == state_before


def test_outside_modified_flags_only_edits_around_the_block(tmp_path: Path) -> None:
    """``outside_modified`` is True for an edit around the block, False for one inside."""
    apply_managed_file(tmp_path, block("OUT.md", "1", "v1"))
    out = tmp_path / "OUT.md"
    out.write_text("HEADER\n" + out.read_text(encoding="utf-8"), encoding="utf-8")
    around = diff_managed_file(tmp_path, block("OUT.md", "2", "v2"))
    assert around.status is ApplyStatus.UPDATE
    assert around.outside_modified is True

    apply_managed_file(tmp_path, block("IN.md", "1", "v1"))
    inside = tmp_path / "IN.md"
    inside.write_text(
        "<!-- PROTEAN:BEGIN protean -->\nhand edit\n<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )
    within = diff_managed_file(tmp_path, block("IN.md", "1", "v1"))
    assert within.outside_modified is False


def test_preexisting_file_without_state_entry_conflicts(tmp_path: Path) -> None:
    """A hand-written target with valid markers but no state entry is a CONFLICT.

    With no state the writer cannot prove it wrote the on-disk content, so it
    refuses to overwrite a file it did not author.
    """
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "<!-- PROTEAN:BEGIN protean -->\nhand written\n<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )
    proj = block("AGENTS.md", "1", "framework block")

    assert diff_managed_file(tmp_path, proj).status is ApplyStatus.CONFLICT
    with pytest.raises(ManagedFileConflict):
        apply_managed_file(tmp_path, proj)
    assert target.read_text(encoding="utf-8") == (
        "<!-- PROTEAN:BEGIN protean -->\nhand written\n<!-- PROTEAN:END protean -->\n"
    )


def test_apply_leaves_no_temp_sibling(tmp_path: Path) -> None:
    """The atomic writes clean up after themselves: no ``.dx-tmp`` file is left."""
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1"))  # create + state write
    apply_managed_file(tmp_path, block("AGENTS.md", "2", "v2"))  # in-place update write
    assert list(tmp_path.rglob("*.dx-tmp")) == []


def test_apply_does_not_clobber_an_existing_dx_tmp_sibling(tmp_path: Path) -> None:
    """A file that already sits at the old fixed temp name survives an apply."""
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1"))
    bystander = tmp_path / "AGENTS.md.dx-tmp"
    bystander.write_text("someone else's file", encoding="utf-8")

    apply_managed_file(tmp_path, block("AGENTS.md", "2", "v2"))

    assert bystander.read_text(encoding="utf-8") == "someone else's file"
    assert "v2" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


def test_apply_preserves_the_target_file_mode(tmp_path: Path) -> None:
    """An update keeps the file's permissions; the temp file's 0600 must not stick."""
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1"))
    target = tmp_path / "AGENTS.md"
    target.chmod(0o640)

    apply_managed_file(tmp_path, block("AGENTS.md", "2", "v2"))

    assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_create_respects_the_process_umask(tmp_path: Path) -> None:
    """A new file follows the umask, not a forced 0644 that could widen it."""
    old = os.umask(0o077)
    try:
        apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1"))
    finally:
        os.umask(old)

    # ``mkstemp`` creates at 0600; forcing 0644 would have made the file
    # world-readable despite the 0077 umask that asked to keep it private.
    assert stat.S_IMODE((tmp_path / "AGENTS.md").stat().st_mode) == 0o600
    assert (
        stat.S_IMODE((tmp_path / ".protean" / "dx-state.json").stat().st_mode) == 0o600
    )


# --- managed JSON keys -----------------------------------------------------


def test_json_merge_updates_managed_keys_and_preserves_the_rest(tmp_path: Path) -> None:
    apply_managed_file(tmp_path, json_keys(".mcp.json", "1", {"servers": {"a": 1}}))
    target = tmp_path / ".mcp.json"
    # A user adds an unmanaged key and a nested unmanaged structure.
    disk = json.loads(target.read_text(encoding="utf-8"))
    disk["userKey"] = {"keep": ["me"]}
    target.write_text(json.dumps(disk, indent=2) + "\n", encoding="utf-8")

    result = apply_managed_file(
        tmp_path, json_keys(".mcp.json", "2", {"servers": {"a": 2}})
    )

    assert result.status is ApplyStatus.UPDATE
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert merged["servers"] == {"a": 2}  # managed key replaced
    assert merged["userKey"] == {"keep": ["me"]}  # unmanaged key preserved


def test_json_create_then_rerun_is_no_op(tmp_path: Path) -> None:
    result = apply_managed_file(
        tmp_path, json_keys(".mcp.json", "1", {"servers": {"a": 1}})
    )
    assert result.status is ApplyStatus.CREATE
    content = (tmp_path / ".mcp.json").read_text(encoding="utf-8")
    assert content.endswith("\n")

    rerun = apply_managed_file(
        tmp_path, json_keys(".mcp.json", "1", {"servers": {"a": 1}})
    )
    assert rerun.status is ApplyStatus.NO_CHANGE


def test_json_conflict_on_hand_edited_managed_key(tmp_path: Path) -> None:
    apply_managed_file(tmp_path, json_keys(".mcp.json", "1", {"servers": {"a": 1}}))
    target = tmp_path / ".mcp.json"
    target.write_text(json.dumps({"servers": {"a": 99}}) + "\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    state_before = state_path(tmp_path).read_text(encoding="utf-8")

    proj = json_keys(".mcp.json", "2", {"servers": {"a": 2}})
    assert diff_managed_file(tmp_path, proj).status is ApplyStatus.CONFLICT
    with pytest.raises(ManagedFileConflict):
        apply_managed_file(tmp_path, proj)
    assert target.read_text(encoding="utf-8") == before
    assert state_path(tmp_path).read_text(encoding="utf-8") == state_before


def test_json_missing_key_is_distinct_from_a_null_key(tmp_path: Path) -> None:
    """A managed key set to null and then deleted on disk is drift, not a no-op.

    ``disk.get(key)`` answers ``None`` for both a missing key and a null one, so
    hashing the values alone would read the deletion as NO_CHANGE and never notice
    the managed key vanished. The slice carries key presence, so the two differ.
    """
    proj = json_keys(".mcp.json", "1", {"x": None})
    apply_managed_file(tmp_path, proj)  # writes {"x": null}, records the state
    target = tmp_path / ".mcp.json"
    target.write_text("{}\n", encoding="utf-8")  # user deletes the managed key

    # Same version: with the values-only slice this read as NO_CHANGE and the
    # deletion was silently accepted. Preserving presence makes it a real change.
    assert diff_managed_file(tmp_path, proj).status is ApplyStatus.CONFLICT


def test_json_non_object_target_raises(tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ManagedFileError, match="must be a JSON object"):
        diff_managed_file(tmp_path, json_keys(".mcp.json", "1", {"servers": {}}))


def test_json_invalid_target_raises(tmp_path: Path) -> None:
    """A managed-JSON-keys target that is not valid JSON is refused, not overwritten."""
    target = tmp_path / ".mcp.json"
    target.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ManagedFileError, match="is not valid JSON"):
        diff_managed_file(tmp_path, json_keys(".mcp.json", "1", {"servers": {}}))
    assert target.read_text(encoding="utf-8") == "{ not valid json"


def test_non_serializable_json_data_is_rejected() -> None:
    """A non-JSON-serializable managed value fails at construction, not at hash time."""
    with pytest.raises(ValueError, match="JSON-serializable"):
        ManagedJsonKeys(target=".mcp.json", version="1", data={"servers": {1, 2}})


def test_non_string_managed_key_is_rejected() -> None:
    """``json.dumps`` would coerce ``1`` to ``"1"``; construction rejects it instead."""
    with pytest.raises(ValueError, match="string keys"):
        ManagedJsonKeys(target=".mcp.json", version="1", data={1: "a"})


def test_non_string_nested_key_is_rejected() -> None:
    """The string-key rule holds all the way down, not just at the managed level."""
    with pytest.raises(ValueError, match="string keys"):
        ManagedJsonKeys(
            target=".mcp.json", version="1", data={"servers": {"a": {2: "b"}}}
        )
    with pytest.raises(ValueError, match="string keys"):
        ManagedJsonKeys(
            target=".mcp.json", version="1", data={"servers": [{None: "b"}]}
        )


def test_string_keyed_nesting_is_accepted(tmp_path: Path) -> None:
    """The key check walks lists and nested dicts without rejecting valid data."""
    data = {"servers": [{"name": "a"}, {"name": "b", "env": {"KEY": "v"}}]}
    apply_managed_file(tmp_path, json_keys(".mcp.json", "1", data))
    assert json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8")) == data


# --- state file ------------------------------------------------------------


def test_state_round_trips_through_to_dict_from_dict() -> None:
    state = ManagedFileState().with_entry(
        "AGENTS.md", FileStateEntry(version="1", file_hash="ff", slice_hash="aa")
    )
    assert ManagedFileState.from_dict(state.to_dict()) == state
    assert state.to_dict()["state_version"] == STATE_VERSION


def test_absent_state_file_reads_as_empty(tmp_path: Path) -> None:
    assert load_state(tmp_path) == ManagedFileState()


def test_malformed_state_file_raises_loudly(tmp_path: Path) -> None:
    (tmp_path / ".protean").mkdir()
    state_path(tmp_path).write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_state(tmp_path)


def test_corrupt_state_file_surfaces_as_managed_file_error(tmp_path: Path) -> None:
    """The public APIs honor their documented ManagedFileError contract.

    ``load_state`` keeps its own ``ValueError`` for direct callers;
    ``diff_managed_file`` and ``apply_managed_file`` translate it, so a caller
    catching ``ManagedFileError`` still sees state-file corruption.
    """
    (tmp_path / ".protean").mkdir()
    state_path(tmp_path).write_text("{ not valid json", encoding="utf-8")

    with pytest.raises(ManagedFileError, match="Invalid JSON"):
        diff_managed_file(tmp_path, block("AGENTS.md", "1", "v1"))
    with pytest.raises(ManagedFileError, match="Invalid JSON"):
        apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1"))


def test_non_utf8_state_file_raises_value_error(tmp_path: Path) -> None:
    """A state file that is not valid utf-8 fails loud as a ValueError."""
    (tmp_path / ".protean").mkdir()
    state_path(tmp_path).write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError, match="not valid utf-8"):
        load_state(tmp_path)


def test_state_entry_missing_a_required_field_is_rejected(tmp_path: Path) -> None:
    """A state entry that omits a field fails loud instead of defaulting."""
    (tmp_path / ".protean").mkdir()
    state_path(tmp_path).write_text(
        json.dumps(
            {
                "state_version": STATE_VERSION,
                "entries": {"AGENTS.md": {"version": "1", "file_hash": "ff"}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required field 'slice_hash'"):
        load_state(tmp_path)


def test_unreadable_state_file_raises_value_error(tmp_path: Path) -> None:
    """An OS-level read failure surfaces as a ValueError, not a raw OSError."""
    (tmp_path / ".protean").mkdir()
    # A directory where the state file belongs: it exists, but reading it raises
    # IsADirectoryError, an OSError.
    state_path(tmp_path).mkdir()
    with pytest.raises(ValueError, match="Could not read"):
        load_state(tmp_path)


def test_unknown_state_version_is_rejected(tmp_path: Path) -> None:
    (tmp_path / ".protean").mkdir()
    state_path(tmp_path).write_text(
        json.dumps({"state_version": "999.0", "entries": {}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Unsupported state_version"):
        load_state(tmp_path)


def test_state_entry_with_non_string_hash_is_rejected(tmp_path: Path) -> None:
    (tmp_path / ".protean").mkdir()
    state_path(tmp_path).write_text(
        json.dumps(
            {
                "state_version": STATE_VERSION,
                "entries": {"AGENTS.md": {"version": "1", "file_hash": 5}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be a string"):
        load_state(tmp_path)


# --- request validation ----------------------------------------------------


def test_empty_block_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="block_id"):
        ManagedBlock(
            target="AGENTS.md",
            version="1",
            block_id="",
            body="body",
            comment_prefix="# ",
        )


def test_marker_syntax_carrying_a_newline_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not contain a newline"):
        ManagedBlock(
            target="AGENTS.md",
            version="1",
            block_id="protean",
            body="body",
            comment_prefix="#\n",
        )


def test_empty_json_data_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one managed key"):
        ManagedJsonKeys(target=".mcp.json", version="1", data={})


def test_merge_mode_reflects_the_request_type() -> None:
    assert block("AGENTS.md", "1", "b").mode is MergeMode.BLOCK
    assert json_keys(".mcp.json", "1", {"a": 1}).mode is MergeMode.JSON_KEYS


def test_state_from_dict_rejects_non_mapping_and_bad_entries() -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        ManagedFileState.from_dict([1, 2, 3])
    with pytest.raises(ValueError, match="'entries' must be an object"):
        ManagedFileState.from_dict({"state_version": STATE_VERSION, "entries": []})
    with pytest.raises(ValueError, match="must be an object"):
        FileStateEntry.from_dict("not-an-object", "AGENTS.md")


def test_hash_stability_ignores_benign_repeats(tmp_path: Path) -> None:
    """Applying the identical artifact twice is stable: one write, then no-op."""
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "line one\nline two"))
    first = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    result = apply_managed_file(tmp_path, block("AGENTS.md", "1", "line one\nline two"))
    assert result.status is ApplyStatus.NO_CHANGE
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == first


# --- line endings ----------------------------------------------------------


def test_crlf_target_reads_as_no_change(tmp_path: Path) -> None:
    """A CRLF checkout of content the writer wrote as LF is not a phantom conflict.

    Reads go through text mode, so both spellings normalize to ``\\n`` before they
    are hashed and the slice still matches what the state file recorded.
    """
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "line one\nline two"))
    target = tmp_path / "AGENTS.md"
    # Normalize to LF first so the conversion is exact whatever the create path
    # wrote: an already-CRLF file would otherwise double to "\r\r\n".
    target.write_bytes(
        target.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    )

    result = diff_managed_file(tmp_path, block("AGENTS.md", "1", "line one\nline two"))

    assert result.status is ApplyStatus.NO_CHANGE
    assert result.outside_modified is False


def test_update_keeps_a_crlf_target_in_crlf(tmp_path: Path) -> None:
    """An update writes back in the line ending the file already uses.

    The writer renders LF; writing that out untranslated would flip every line
    outside the managed block too, which the block merge promises not to touch.
    """
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1 body"))
    target = tmp_path / "AGENTS.md"
    # Normalize to LF first so an already-CRLF create path does not double to
    # "\r\r\n" and invalidate the CRLF-preservation check below.
    crlf = target.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    target.write_bytes(crlf + b"user tail\r\n")

    assert apply_managed_file(tmp_path, block("AGENTS.md", "2", "v2 body")).status is (
        ApplyStatus.UPDATE
    )

    raw = target.read_bytes()
    assert b"v2 body" in raw and b"user tail" in raw
    # Every LF is still part of a CRLF pair: no line ending was rewritten.
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_update_keeps_an_lf_target_in_lf(tmp_path: Path) -> None:
    """An LF file stays LF, whatever the platform's own line ending is."""
    apply_managed_file(tmp_path, block("AGENTS.md", "1", "v1 body"))
    target = tmp_path / "AGENTS.md"
    # Force the created file to LF first so the update is what's under test, not
    # whatever line ending the create path happened to write on this platform.
    target.write_bytes(target.read_bytes().replace(b"\r\n", b"\n"))
    apply_managed_file(tmp_path, block("AGENTS.md", "2", "v2 body"))

    assert b"\r" not in target.read_bytes()
    assert b"\r" not in state_path(tmp_path).read_bytes()


# --- symlink targets -------------------------------------------------------


def test_dangling_symlink_target_is_refused(tmp_path: Path) -> None:
    """A dangling symlink is not a free path to create over.

    ``Path.exists()`` follows the link and reads ``False`` for a broken one, so
    without the symlink-aware check the diff would say CREATE while ``apply_plan``,
    which is symlink-aware, would then raise from underneath.
    """
    link = tmp_path / "AGENTS.md"
    link.symlink_to(tmp_path / "does-not-exist")
    proj = block("AGENTS.md", "1", "framework block")

    for call in (diff_managed_file, apply_managed_file):
        with pytest.raises(ManagedFileError) as excinfo:
            call(tmp_path, proj)
        assert "symlink" in str(excinfo.value)

    assert link.is_symlink() and not link.exists()
    assert not state_path(tmp_path).exists()


def test_symlink_to_a_real_target_is_refused(tmp_path: Path) -> None:
    """A live symlink is refused too: the update would swap it for a regular file.

    ``os.replace`` renames over the link itself, so the real file behind it would
    keep the old content while the link's path silently stopped being a link.
    """
    real = tmp_path / "real.md"
    apply_managed_file(tmp_path, block("real.md", "1", "v1 body"))
    original = real.read_bytes()
    link = tmp_path / "AGENTS.md"
    link.symlink_to(real)

    with pytest.raises(ManagedFileError) as excinfo:
        apply_managed_file(tmp_path, block("AGENTS.md", "2", "v2 body"))

    assert "symlink" in str(excinfo.value)
    assert link.is_symlink()
    assert real.read_bytes() == original


def test_symlinked_state_directory_is_refused(tmp_path: Path) -> None:
    """A ``.protean`` symlink would let the state read/write escape the project root."""
    outside = tmp_path.parent / "outside_dot_protean"
    outside.mkdir()
    (tmp_path / ".protean").symlink_to(outside, target_is_directory=True)
    proj = block("AGENTS.md", "1", "framework block")

    with pytest.raises(ManagedFileError, match="symlink"):
        load_state(tmp_path)
    for call in (diff_managed_file, apply_managed_file):
        with pytest.raises(ManagedFileError, match="symlink"):
            call(tmp_path, proj)

    # Nothing was written through the link.
    assert not (outside / "dx-state.json").exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_symlinked_state_file_is_refused(tmp_path: Path) -> None:
    """A ``dx-state.json`` symlink would let a write follow the link outside the tree."""
    (tmp_path / ".protean").mkdir()
    outside = tmp_path.parent / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    state_path(tmp_path).symlink_to(outside)

    with pytest.raises(ManagedFileError, match="symlink"):
        apply_managed_file(tmp_path, block("AGENTS.md", "1", "framework block"))

    assert outside.read_text(encoding="utf-8") == "{}"


# --- targets outside the project root --------------------------------------


def test_absolute_target_is_refused(tmp_path: Path) -> None:
    """An absolute target would discard the root and write anywhere on disk.

    ``root / "/abs/path"`` is ``/abs/path``, so the containment check below cannot
    catch it; only the absolute-path check does.
    """
    outside = tmp_path.parent / "outside.md"
    outside.write_text("user content\n", encoding="utf-8")
    proj = block(str(outside), "1", "framework block")

    for call in (diff_managed_file, apply_managed_file):
        with pytest.raises(ManagedFileError) as excinfo:
            call(tmp_path / "project", proj)
        assert "absolute" in str(excinfo.value)

    assert outside.read_text(encoding="utf-8") == "user content\n"


def test_target_climbing_out_with_dotdot_is_refused(tmp_path: Path) -> None:
    """A ``..`` segment must not carry an update out of the project."""
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"kept": 1}\n', encoding="utf-8")
    proj = json_keys("../outside.json", "1", {"servers": {}})

    for call in (diff_managed_file, apply_managed_file):
        with pytest.raises(ManagedFileError) as excinfo:
            call(root, proj)
        assert "outside the project root" in str(excinfo.value)

    assert outside.read_text(encoding="utf-8") == '{"kept": 1}\n'
    assert not state_path(root).exists()


def test_target_under_a_symlinked_directory_is_refused(tmp_path: Path) -> None:
    """A symlinked parent directory climbs out of the root just as ``..`` does.

    The symlink check reads the final component only, so this is caught by
    resolving the whole path before the containment test.
    """
    root = tmp_path / "project"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "AGENTS.md").write_text("user content\n", encoding="utf-8")
    (root / "link").symlink_to(elsewhere, target_is_directory=True)
    proj = block("link/AGENTS.md", "1", "framework block")

    for call in (diff_managed_file, apply_managed_file):
        with pytest.raises(ManagedFileError) as excinfo:
            call(root, proj)
        assert "outside the project root" in str(excinfo.value)

    assert (elsewhere / "AGENTS.md").read_text(encoding="utf-8") == "user content\n"


def test_empty_target_is_refused(tmp_path: Path) -> None:
    """An empty target names the project root itself, which is a directory."""
    with pytest.raises(ManagedFileError) as excinfo:
        diff_managed_file(tmp_path, block("", "1", "framework block"))

    assert "non-empty" in str(excinfo.value)
