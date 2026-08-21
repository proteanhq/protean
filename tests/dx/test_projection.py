"""Behavioral tests for the idempotent file-projection engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from protean.dx.projection import (
    LOCK_VERSION,
    ManagedRegionProjection,
    ProjectionConflict,
    ProjectionEntry,
    ProjectionError,
    ProjectionLock,
    ProjectionMode,
    ProjectionStatus,
    StructuredJsonProjection,
    apply_projection,
    diff_projection,
    load_lock,
)

# --- helpers ---------------------------------------------------------------


def region(target: str, version: str, body: str) -> ManagedRegionProjection:
    """An HTML-comment managed-region projection for AGENTS.md-style files."""
    return ManagedRegionProjection(
        target=target,
        version=version,
        region_id="protean",
        body=body,
        comment_prefix="<!-- ",
        comment_suffix=" -->",
    )


def structured(target: str, version: str, data: dict) -> StructuredJsonProjection:
    return StructuredJsonProjection(target=target, version=version, data=data)


def lock_path(root: Path) -> Path:
    return root / ".protean" / "dx.lock"


# --- managed region --------------------------------------------------------


def test_create_writes_region_and_lock_then_rerun_is_no_op(tmp_path: Path) -> None:
    """Create path: project into an absent target, then a re-run is NO_CHANGE."""
    result = apply_projection(tmp_path, region("AGENTS.md", "1", "v1 block"))

    assert result.status is ProjectionStatus.CREATE
    target = tmp_path / "AGENTS.md"
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert content == (
        "<!-- PROTEAN:BEGIN protean -->\nv1 block\n<!-- PROTEAN:END protean -->\n"
    )
    assert content.endswith("\n")  # trailing newline, byte-for-byte hashing input
    assert lock_path(tmp_path).exists()

    rerun = apply_projection(tmp_path, region("AGENTS.md", "1", "v1 block"))
    assert rerun.status is ProjectionStatus.NO_CHANGE
    assert target.read_text(encoding="utf-8") == content


def test_update_preserves_user_text_outside_region(tmp_path: Path) -> None:
    """Re-projecting updates only the managed body; user text around it survives."""
    apply_projection(tmp_path, region("AGENTS.md", "1", "v1 block"))
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "USER TOP\n" + target.read_text(encoding="utf-8") + "USER BOTTOM\n",
        encoding="utf-8",
    )

    result = apply_projection(tmp_path, region("AGENTS.md", "2", "v2 block"))

    assert result.status is ProjectionStatus.UPDATE
    updated = target.read_text(encoding="utf-8")
    assert updated == (
        "USER TOP\n"
        "<!-- PROTEAN:BEGIN protean -->\nv2 block\n<!-- PROTEAN:END protean -->\n"
        "USER BOTTOM\n"
    )


def test_edit_outside_region_still_updates_and_is_reported(tmp_path: Path) -> None:
    """An edit outside the markers is safe: the region updates and the edit lives."""
    apply_projection(tmp_path, region("AGENTS.md", "1", "v1 block"))
    target = tmp_path / "AGENTS.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "EXTRA USER LINE\n", encoding="utf-8"
    )

    result = apply_projection(tmp_path, region("AGENTS.md", "2", "v2 block"))

    assert result.status is ProjectionStatus.UPDATE
    assert result.outside_modified is True
    updated = target.read_text(encoding="utf-8")
    assert "v2 block" in updated
    assert "v1 block" not in updated
    assert updated.endswith("EXTRA USER LINE\n")


def test_conflict_on_user_edit_inside_region_writes_nothing(tmp_path: Path) -> None:
    """A user edit inside the markers is a CONFLICT: diff reports it, apply refuses."""
    apply_projection(tmp_path, region("AGENTS.md", "1", "v1 block"))
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "<!-- PROTEAN:BEGIN protean -->\nhacked by user\n"
        "<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )
    before = target.read_text(encoding="utf-8")
    lock_before = lock_path(tmp_path).read_text(encoding="utf-8")

    proj = region("AGENTS.md", "2", "v2 block")
    diff = diff_projection(tmp_path, proj)
    assert diff.status is ProjectionStatus.CONFLICT
    assert diff.content is None
    # The edit is inside the region, so the drift is not "outside".
    assert diff.outside_modified is False

    with pytest.raises(ProjectionConflict) as excinfo:
        apply_projection(tmp_path, proj)
    assert excinfo.value.target == "AGENTS.md"
    assert "protean" in excinfo.value.region

    assert target.read_text(encoding="utf-8") == before  # nothing written
    assert lock_path(tmp_path).read_text(encoding="utf-8") == lock_before


def test_user_edit_equal_to_new_content_is_not_a_conflict(tmp_path: Path) -> None:
    """If the user's edit happens to equal the incoming content, it is no conflict.

    The region body already matches the new render, so there is no data to lose.
    The version advanced, so the engine records a safe UPDATE (an identical write
    that advances the lock) rather than blocking.
    """
    apply_projection(tmp_path, region("AGENTS.md", "1", "A"))
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "<!-- PROTEAN:BEGIN protean -->\nB\n<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )

    result = apply_projection(tmp_path, region("AGENTS.md", "2", "B"))

    assert result.status is ProjectionStatus.UPDATE
    assert (
        target.read_text(encoding="utf-8")
        == "<!-- PROTEAN:BEGIN protean -->\nB\n<!-- PROTEAN:END protean -->\n"
    )
    # The lock advanced to the new version, so a further re-run is a no-op.
    assert apply_projection(tmp_path, region("AGENTS.md", "2", "B")).status is (
        ProjectionStatus.NO_CHANGE
    )


def test_missing_end_marker_raises_and_does_not_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    original = "<!-- PROTEAN:BEGIN protean -->\nbody with no end\n"
    target.write_text(original, encoding="utf-8")

    with pytest.raises(ProjectionError, match="missing its marker"):
        apply_projection(tmp_path, region("AGENTS.md", "1", "new"))
    assert target.read_text(encoding="utf-8") == original


def test_no_markers_raises(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_text("just some prose, no markers\n", encoding="utf-8")

    with pytest.raises(ProjectionError, match="missing its marker"):
        diff_projection(tmp_path, region("AGENTS.md", "1", "new"))


def test_duplicate_begin_markers_raise(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "<!-- PROTEAN:BEGIN protean -->\na\n<!-- PROTEAN:END protean -->\n"
        "<!-- PROTEAN:BEGIN protean -->\nb\n<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )
    with pytest.raises(ProjectionError, match="copies of the marker"):
        diff_projection(tmp_path, region("AGENTS.md", "1", "new"))


def test_reversed_markers_raise(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "<!-- PROTEAN:END protean -->\nbody\n<!-- PROTEAN:BEGIN protean -->\n",
        encoding="utf-8",
    )
    with pytest.raises(ProjectionError, match="end marker before"):
        diff_projection(tmp_path, region("AGENTS.md", "1", "new"))


def test_prefix_region_id_does_not_false_match(tmp_path: Path) -> None:
    """A region id that is a prefix of another does not match the longer one.

    With an empty comment suffix, ``protean`` is a plain substring of
    ``protean-extra``. Line-anchored marker matching must not treat the
    ``protean-extra`` region as the ``protean`` region.
    """
    target = tmp_path / "config.ini"
    target.write_text(
        "# PROTEAN:BEGIN protean-extra\nother tool block\n# PROTEAN:END protean-extra\n",
        encoding="utf-8",
    )
    proj = ManagedRegionProjection(
        target="config.ini",
        version="1",
        region_id="protean",
        body="framework block",
        comment_prefix="# ",
    )
    with pytest.raises(ProjectionError, match="missing its marker"):
        diff_projection(tmp_path, proj)
    # The other tool's block is left untouched.
    assert target.read_text(encoding="utf-8") == (
        "# PROTEAN:BEGIN protean-extra\nother tool block\n# PROTEAN:END protean-extra\n"
    )


def test_prefix_region_id_updates_only_its_own_region(tmp_path: Path) -> None:
    """Two regions whose ids share a prefix are told apart; only the named one moves."""
    v1 = ManagedRegionProjection(
        target="config.ini",
        version="1",
        region_id="protean",
        body="framework v1",
        comment_prefix="# ",
    )
    apply_projection(tmp_path, v1)  # establishes the lock for the protean region
    target = tmp_path / "config.ini"
    # A second tool appends its own region whose id starts with "protean".
    target.write_text(
        target.read_text(encoding="utf-8")
        + "# PROTEAN:BEGIN protean-extra\nother tool block\n"
        "# PROTEAN:END protean-extra\n",
        encoding="utf-8",
    )

    v2 = ManagedRegionProjection(
        target="config.ini",
        version="2",
        region_id="protean",
        body="framework v2",
        comment_prefix="# ",
    )
    merged = diff_projection(tmp_path, v2)
    assert merged.status is ProjectionStatus.UPDATE
    assert merged.content == (
        "# PROTEAN:BEGIN protean\nframework v2\n# PROTEAN:END protean\n"
        "# PROTEAN:BEGIN protean-extra\nother tool block\n# PROTEAN:END protean-extra\n"
    )


def test_body_containing_a_marker_line_is_rejected() -> None:
    """A body line identical to a marker would frame a phantom region: reject it."""
    with pytest.raises(ValueError, match="identical to a region marker"):
        ManagedRegionProjection(
            target="config.ini",
            version="1",
            region_id="protean",
            body="# PROTEAN:END protean",
            comment_prefix="# ",
        )


def test_non_utf8_target_raises_projection_error(tmp_path: Path) -> None:
    """A non-utf-8 managed-region target fails as a ProjectionError, not a raw decode."""
    target = tmp_path / "AGENTS.md"
    target.write_bytes(b"\xff\xfe not utf-8 at all")
    with pytest.raises(ProjectionError, match="not valid utf-8"):
        diff_projection(tmp_path, region("AGENTS.md", "1", "new"))


def test_hash_mode_uses_comment_syntax_config(tmp_path: Path) -> None:
    """A ``#``-comment config target projects and re-projects idempotently."""
    proj = ManagedRegionProjection(
        target="config.ini",
        version="1",
        region_id="protean",
        body="key = value",
        comment_prefix="# ",
    )
    result = apply_projection(tmp_path, proj)
    assert result.status is ProjectionStatus.CREATE
    assert (tmp_path / "config.ini").read_text(encoding="utf-8") == (
        "# PROTEAN:BEGIN protean\nkey = value\n# PROTEAN:END protean\n"
    )


def test_version_bump_with_identical_body_updates_and_advances_lock(
    tmp_path: Path,
) -> None:
    """A re-install (version bumped, same body, untouched file) is a safe UPDATE.

    The region is untouched, so the write is safe; the lock must advance to the
    new version so the next identical re-run reads as a no-op.
    """
    apply_projection(tmp_path, region("AGENTS.md", "1", "same body"))

    result = apply_projection(tmp_path, region("AGENTS.md", "2", "same body"))
    assert result.status is ProjectionStatus.UPDATE

    rerun = apply_projection(tmp_path, region("AGENTS.md", "2", "same body"))
    assert rerun.status is ProjectionStatus.NO_CHANGE


def test_no_change_leaves_the_lockfile_untouched(tmp_path: Path) -> None:
    """A NO_CHANGE re-run must not rewrite the lockfile."""
    apply_projection(tmp_path, region("AGENTS.md", "1", "block"))
    lock_before = lock_path(tmp_path).read_text(encoding="utf-8")

    result = apply_projection(tmp_path, region("AGENTS.md", "1", "block"))
    assert result.status is ProjectionStatus.NO_CHANGE
    assert lock_path(tmp_path).read_text(encoding="utf-8") == lock_before


def test_outside_modified_flags_only_edits_around_the_region(tmp_path: Path) -> None:
    """``outside_modified`` is True for an edit around the region, False for one inside."""
    apply_projection(tmp_path, region("OUT.md", "1", "v1"))
    out = tmp_path / "OUT.md"
    out.write_text("HEADER\n" + out.read_text(encoding="utf-8"), encoding="utf-8")
    around = diff_projection(tmp_path, region("OUT.md", "2", "v2"))
    assert around.status is ProjectionStatus.UPDATE
    assert around.outside_modified is True

    apply_projection(tmp_path, region("IN.md", "1", "v1"))
    inside = tmp_path / "IN.md"
    inside.write_text(
        "<!-- PROTEAN:BEGIN protean -->\nhand edit\n<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )
    within = diff_projection(tmp_path, region("IN.md", "1", "v1"))
    assert within.outside_modified is False


def test_preexisting_file_without_lock_entry_conflicts(tmp_path: Path) -> None:
    """A hand-written target with valid markers but no lock entry is a CONFLICT.

    With no lock the engine cannot prove it wrote the on-disk content, so it
    refuses to overwrite a file it did not author.
    """
    target = tmp_path / "AGENTS.md"
    target.write_text(
        "<!-- PROTEAN:BEGIN protean -->\nhand written\n<!-- PROTEAN:END protean -->\n",
        encoding="utf-8",
    )
    proj = region("AGENTS.md", "1", "framework block")

    assert diff_projection(tmp_path, proj).status is ProjectionStatus.CONFLICT
    with pytest.raises(ProjectionConflict):
        apply_projection(tmp_path, proj)
    assert target.read_text(encoding="utf-8") == (
        "<!-- PROTEAN:BEGIN protean -->\nhand written\n<!-- PROTEAN:END protean -->\n"
    )


def test_apply_leaves_no_temp_sibling(tmp_path: Path) -> None:
    """The atomic writes clean up after themselves: no ``.dx-tmp`` file is left."""
    apply_projection(tmp_path, region("AGENTS.md", "1", "v1"))  # create + lock write
    apply_projection(tmp_path, region("AGENTS.md", "2", "v2"))  # in-place update write
    assert list(tmp_path.rglob("*.dx-tmp")) == []


# --- structured JSON -------------------------------------------------------


def test_json_merge_updates_managed_keys_and_preserves_the_rest(tmp_path: Path) -> None:
    apply_projection(tmp_path, structured(".mcp.json", "1", {"servers": {"a": 1}}))
    target = tmp_path / ".mcp.json"
    # A user adds an unmanaged key and a nested unmanaged structure.
    disk = json.loads(target.read_text(encoding="utf-8"))
    disk["userKey"] = {"keep": ["me"]}
    target.write_text(json.dumps(disk, indent=2) + "\n", encoding="utf-8")

    result = apply_projection(
        tmp_path, structured(".mcp.json", "2", {"servers": {"a": 2}})
    )

    assert result.status is ProjectionStatus.UPDATE
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert merged["servers"] == {"a": 2}  # managed key replaced
    assert merged["userKey"] == {"keep": ["me"]}  # unmanaged key preserved


def test_json_create_then_rerun_is_no_op(tmp_path: Path) -> None:
    result = apply_projection(
        tmp_path, structured(".mcp.json", "1", {"servers": {"a": 1}})
    )
    assert result.status is ProjectionStatus.CREATE
    content = (tmp_path / ".mcp.json").read_text(encoding="utf-8")
    assert content.endswith("\n")

    rerun = apply_projection(
        tmp_path, structured(".mcp.json", "1", {"servers": {"a": 1}})
    )
    assert rerun.status is ProjectionStatus.NO_CHANGE


def test_json_conflict_on_hand_edited_managed_key(tmp_path: Path) -> None:
    apply_projection(tmp_path, structured(".mcp.json", "1", {"servers": {"a": 1}}))
    target = tmp_path / ".mcp.json"
    target.write_text(json.dumps({"servers": {"a": 99}}) + "\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    lock_before = lock_path(tmp_path).read_text(encoding="utf-8")

    proj = structured(".mcp.json", "2", {"servers": {"a": 2}})
    assert diff_projection(tmp_path, proj).status is ProjectionStatus.CONFLICT
    with pytest.raises(ProjectionConflict):
        apply_projection(tmp_path, proj)
    assert target.read_text(encoding="utf-8") == before
    assert lock_path(tmp_path).read_text(encoding="utf-8") == lock_before


def test_json_non_object_target_raises(tmp_path: Path) -> None:
    target = tmp_path / ".mcp.json"
    target.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ProjectionError, match="must be a JSON object"):
        diff_projection(tmp_path, structured(".mcp.json", "1", {"servers": {}}))


def test_non_serializable_structured_data_is_rejected() -> None:
    """A non-JSON-serializable managed value fails at construction, not at hash time."""
    with pytest.raises(ValueError, match="JSON-serializable"):
        StructuredJsonProjection(
            target=".mcp.json", version="1", data={"servers": {1, 2}}
        )


# --- lockfile --------------------------------------------------------------


def test_lock_round_trips_through_to_dict_from_dict() -> None:
    lock = ProjectionLock().with_entry(
        "AGENTS.md", ProjectionEntry(version="1", file_hash="ff", slice_hash="aa")
    )
    assert ProjectionLock.from_dict(lock.to_dict()) == lock
    assert lock.to_dict()["lock_version"] == LOCK_VERSION


def test_absent_lockfile_reads_as_empty(tmp_path: Path) -> None:
    assert load_lock(tmp_path) == ProjectionLock()


def test_malformed_lockfile_raises_loudly(tmp_path: Path) -> None:
    (tmp_path / ".protean").mkdir()
    lock_path(tmp_path).write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid JSON"):
        load_lock(tmp_path)


def test_non_utf8_lockfile_raises_value_error(tmp_path: Path) -> None:
    """A lockfile that is not valid utf-8 fails loud as a ValueError."""
    (tmp_path / ".protean").mkdir()
    lock_path(tmp_path).write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ValueError, match="not valid utf-8"):
        load_lock(tmp_path)


def test_unknown_lock_version_is_rejected(tmp_path: Path) -> None:
    (tmp_path / ".protean").mkdir()
    lock_path(tmp_path).write_text(
        json.dumps({"lock_version": "999.0", "entries": {}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="Unsupported lock_version"):
        load_lock(tmp_path)


def test_lock_entry_with_non_string_hash_is_rejected(tmp_path: Path) -> None:
    (tmp_path / ".protean").mkdir()
    lock_path(tmp_path).write_text(
        json.dumps(
            {
                "lock_version": LOCK_VERSION,
                "entries": {"AGENTS.md": {"version": "1", "file_hash": 5}},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must be a string"):
        load_lock(tmp_path)


# --- request validation ----------------------------------------------------


def test_empty_region_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="region_id"):
        ManagedRegionProjection(
            target="AGENTS.md",
            version="1",
            region_id="",
            body="body",
            comment_prefix="# ",
        )


def test_marker_syntax_carrying_a_newline_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not contain a newline"):
        ManagedRegionProjection(
            target="AGENTS.md",
            version="1",
            region_id="protean",
            body="body",
            comment_prefix="#\n",
        )


def test_empty_structured_data_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one managed key"):
        StructuredJsonProjection(target=".mcp.json", version="1", data={})


def test_projection_mode_reflects_the_request_type() -> None:
    assert region("AGENTS.md", "1", "b").mode is ProjectionMode.MANAGED_REGION
    assert structured(".mcp.json", "1", {"a": 1}).mode is ProjectionMode.STRUCTURED_JSON


def test_lock_from_dict_rejects_non_mapping_and_bad_entries() -> None:
    with pytest.raises(ValueError, match="must be a mapping"):
        ProjectionLock.from_dict([1, 2, 3])
    with pytest.raises(ValueError, match="'entries' must be an object"):
        ProjectionLock.from_dict({"lock_version": LOCK_VERSION, "entries": []})
    with pytest.raises(ValueError, match="must be an object"):
        ProjectionEntry.from_dict("not-an-object", "AGENTS.md")


def test_hash_stability_ignores_benign_repeats(tmp_path: Path) -> None:
    """Projecting the identical artifact twice is stable: one write, then no-op."""
    apply_projection(tmp_path, region("AGENTS.md", "1", "line one\nline two"))
    first = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    result = apply_projection(tmp_path, region("AGENTS.md", "1", "line one\nline two"))
    assert result.status is ProjectionStatus.NO_CHANGE
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == first
