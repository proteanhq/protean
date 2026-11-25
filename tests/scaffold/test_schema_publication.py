"""Guard the published scaffold ChangePlan schema against drift from the packaged schema.

The packaged schema under ``src/protean/scaffold/schema/vX/schema.json`` is the source of
truth. The published copy under ``docs/assets/scaffold/vX/schema.json`` is what the
docs site serves to consumers, and it must be a byte-identical copy. The
schema's ``$id`` names the URL the published copy is served from.
"""

import json
from pathlib import Path

import pytest

# This file is tests/scaffold/test_schema_publication.py, so parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKAGED_SCHEMA_ROOT = _REPO_ROOT / "src" / "protean" / "scaffold" / "schema"
_PUBLISHED_SCHEMA_ROOT = _REPO_ROOT / "docs" / "assets" / "scaffold"


def _packaged_schema_files() -> list[Path]:
    """Every packaged ``schema.json`` under a versioned directory."""
    return sorted(_PACKAGED_SCHEMA_ROOT.glob("v*/schema.json"))


@pytest.mark.no_test_domain
class TestSchemaPublication:
    """Published scaffold ChangePlan schemas mirror the packaged schemas byte-for-byte."""

    def test_at_least_one_packaged_schema_exists(self):
        # Without this, the parametrized tests below pass vacuously when the
        # glob returns nothing, such as after a moved directory.
        packaged = _packaged_schema_files()
        assert len(packaged) > 0, (
            f"Expected packaged schemas under {_PACKAGED_SCHEMA_ROOT} but found none"
        )

    @pytest.mark.parametrize(
        "packaged_schema",
        _packaged_schema_files(),
        ids=lambda p: p.parent.name,
    )
    def test_published_copy_exists(self, packaged_schema: Path):
        published = _PUBLISHED_SCHEMA_ROOT / packaged_schema.parent.name / "schema.json"
        assert published.is_file(), (
            f"Packaged schema {packaged_schema} has no published copy at "
            f"{published}. Publish it by copying the packaged schema verbatim."
        )

    @pytest.mark.parametrize(
        "packaged_schema",
        _packaged_schema_files(),
        ids=lambda p: p.parent.name,
    )
    def test_published_copy_is_byte_identical(self, packaged_schema: Path):
        published = _PUBLISHED_SCHEMA_ROOT / packaged_schema.parent.name / "schema.json"
        assert published.read_bytes() == packaged_schema.read_bytes(), (
            f"Published schema {published} has drifted from packaged schema "
            f"{packaged_schema}. Re-sync by copying the packaged schema verbatim."
        )

    @pytest.mark.parametrize(
        "packaged_schema",
        _packaged_schema_files(),
        ids=lambda p: p.parent.name,
    )
    def test_schema_id_is_the_url_it_is_served_from(self, packaged_schema: Path):
        # mkdocs serves ``docs/assets/scaffold/<version>/schema.json`` at this URL.
        version_dir = packaged_schema.parent.name
        schema = json.loads(packaged_schema.read_text(encoding="utf-8"))
        assert schema["$id"] == (
            f"https://docs.proteanhq.com/assets/scaffold/{version_dir}/schema.json"
        )
