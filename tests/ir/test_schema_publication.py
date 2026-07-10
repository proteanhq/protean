"""Guard the published IR schema against drift from the runtime schema.

The runtime schema under ``src/protean/ir/schema/vX/schema.json`` is the source
of truth — ``IRBuilder`` emits against it and examples validate against it. The
published copy under ``docs/assets/ir/vX/schema.json`` (served to consumers) must
be a **byte-identical** copy. Any structural change to the runtime schema that
forgets to re-publish the docs copy fails these tests, which run in the core
suite (and therefore in CI).
"""

from pathlib import Path

import pytest

# Repo root: tests/ir/test_schema_publication.py → parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_SCHEMA_ROOT = _REPO_ROOT / "src" / "protean" / "ir" / "schema"
_PUBLISHED_SCHEMA_ROOT = _REPO_ROOT / "docs" / "assets" / "ir"


def _runtime_schema_files() -> list[Path]:
    """Every runtime ``schema.json`` under a versioned directory."""
    return sorted(_RUNTIME_SCHEMA_ROOT.glob("v*/schema.json"))


@pytest.mark.no_test_domain
class TestSchemaPublication:
    """Published schemas mirror the runtime schemas byte-for-byte."""

    def test_at_least_one_runtime_schema_exists(self):
        # Guard against the parametrized tests below passing vacuously if the
        # glob ever returns nothing (e.g. a moved directory).
        runtime = _runtime_schema_files()
        assert len(runtime) > 0, (
            f"Expected runtime schemas under {_RUNTIME_SCHEMA_ROOT} but found none"
        )

    @pytest.mark.parametrize(
        "runtime_schema",
        _runtime_schema_files(),
        ids=lambda p: p.parent.name,
    )
    def test_published_copy_exists(self, runtime_schema: Path):
        version_dir = runtime_schema.parent.name
        published = _PUBLISHED_SCHEMA_ROOT / version_dir / "schema.json"
        assert published.exists(), (
            f"Runtime schema {runtime_schema} has no published copy at {published}. "
            "Publish it by copying the runtime schema verbatim."
        )

    @pytest.mark.parametrize(
        "runtime_schema",
        _runtime_schema_files(),
        ids=lambda p: p.parent.name,
    )
    def test_published_copy_is_byte_identical(self, runtime_schema: Path):
        version_dir = runtime_schema.parent.name
        published = _PUBLISHED_SCHEMA_ROOT / version_dir / "schema.json"
        assert published.exists(), (
            f"Runtime schema {runtime_schema} has no published copy at {published}. "
            "Publish it by copying the runtime schema verbatim."
        )
        assert published.read_bytes() == runtime_schema.read_bytes(), (
            f"Published schema {published} has drifted from runtime schema "
            f"{runtime_schema}. Re-sync by copying the runtime schema verbatim."
        )
