"""Diagnostics: TestUnsourcedProjectionField.

UNSOURCED_PROJECTION_FIELD flags a projection field no projector write fills. The
rule reads projector method bodies through the behavioral substrate, so the
projections and projectors live in
:mod:`tests.ir.support.unsourced_projection_domain.catalog`, real importable
source. The corpus is registered as one domain and the IR is built once.
"""

from pathlib import Path

import pytest

from protean import Domain
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.ir.support import unsourced_projection_domain as _pkg
from tests.ir.support.unsourced_projection_domain import catalog

CORPUS_ROOT = str(Path(_pkg.__file__).parent)


def _flagged(ir: dict) -> list[dict]:
    """Diagnostics with code ``UNSOURCED_PROJECTION_FIELD``."""
    return [d for d in ir["diagnostics"] if d["code"] == "UNSOURCED_PROJECTION_FIELD"]


def _fields_for(ir: dict, projection: type) -> list[str]:
    """The field names flagged on one projection, in emission order."""
    element = fqn(projection)
    return [d["field"] for d in _flagged(ir) if d["element"] == element]


@pytest.fixture(scope="module")
def flagged_ir() -> dict:
    """The shared corpus registered as one domain, built once.

    Every projection and its projector(s) are registered together so a single
    build exercises every branch: the four-of-five positive, full coverage by
    attribute write, the empty-evidence guard, a dynamic ``**kwargs``
    construction, the identity exemption, and the two-projector union.
    """
    domain = Domain(name="UnsourcedProjectionField", root_path=CORPUS_ROOT)
    domain.register(catalog.Thing)
    domain.register(catalog.ThingHappened, part_of=catalog.Thing)
    domain.register(catalog.OtherHappened, part_of=catalog.Thing)
    for projection in (
        catalog.PartialProjection,
        catalog.FullProjection,
        catalog.GuardProjection,
        catalog.DynamicProjection,
        catalog.IdentityOnlyProjection,
        catalog.MultiProjection,
    ):
        domain.register(projection)
    domain.register(
        catalog.PartialProjector,
        projector_for=catalog.PartialProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.FullProjector,
        projector_for=catalog.FullProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.GuardProjector,
        projector_for=catalog.GuardProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.DynamicProjector,
        projector_for=catalog.DynamicProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.IdentityOnlyProjector,
        projector_for=catalog.IdentityOnlyProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.MultiProjectorA,
        projector_for=catalog.MultiProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.MultiProjectorB,
        projector_for=catalog.MultiProjection,
        aggregates=[catalog.Thing],
    )
    domain.init(traverse=False)
    return IRBuilder(domain).build()


class TestUnsourcedProjectionField:
    """The rule flags a projection field no projector write fills, and leaves the
    sourced, dynamically-built, unobservable, and identity fields alone."""

    def test_the_rule_is_active(self, flagged_ir):
        """A guard so every absence assertion below is non-vacuous: the corpus
        genuinely produces findings, so a ``field not in ...`` check is a real
        exclusion, not an empty-list pass."""
        assert len(_flagged(flagged_ir)) > 0

    # ── Positive: four of five written, the fifth flagged by name ────────

    def test_unwritten_field_flagged_by_name(self, flagged_ir):
        """``PartialProjector`` writes four fields; ``city`` is flagged, named in
        the message and carried on the ``field`` key."""
        assert _fields_for(flagged_ir, catalog.PartialProjection) == ["city"]
        finding = next(
            d
            for d in _flagged(flagged_ir)
            if d["element"] == fqn(catalog.PartialProjection)
        )
        assert "city" in finding["message"]
        assert finding["level"] == "info"
        assert finding["category"] == "handler_completeness"

    def test_written_fields_not_flagged(self, flagged_ir):
        """The four keyword-written fields are sourced, so none is flagged."""
        flagged = _fields_for(flagged_ir, catalog.PartialProjection)
        for sourced in ("name", "email", "status", "region"):
            assert sourced not in flagged

    # ── Negatives ────────────────────────────────────────────────────────

    def test_full_coverage_by_attribute_write_flags_nothing(self, flagged_ir):
        """``FullProjector`` covers every field by attribute write, so the
        attribute-evidence branch sources them all and nothing is flagged."""
        assert _fields_for(flagged_ir, catalog.FullProjection) == []

    def test_no_observable_writes_flags_nothing(self, flagged_ir):
        """The evidence guard: ``GuardProjector`` builds its record through a
        helper the analysis cannot follow, so the projection is skipped rather
        than reported field-by-field."""
        # The projection is present in the IR, so the empty result is a real
        # skip, not a missing projection.
        assert fqn(catalog.GuardProjection) in flagged_ir["projections"]
        assert _fields_for(flagged_ir, catalog.GuardProjection) == []

    def test_dynamic_construction_flags_nothing(self, flagged_ir):
        """A ``**kwargs`` construction disables the check for the projection even
        though ``second`` is never named."""
        assert _fields_for(flagged_ir, catalog.DynamicProjection) == []

    def test_identity_field_never_flagged(self, flagged_ir):
        """``IdentityOnlyProjection``'s only unwritten field is its
        ``identity_field`` (``key``), which is exempt, so nothing is flagged."""
        assert _fields_for(flagged_ir, catalog.IdentityOnlyProjection) == []
        assert "key" not in _fields_for(flagged_ir, catalog.PartialProjection)

    def test_coverage_is_the_union_across_projectors(self, flagged_ir):
        """``MultiProjectorA`` covers ``alpha`` and ``MultiProjectorB`` covers
        ``beta``; only ``gamma`` (covered by neither) is flagged. A
        per-projector check would wrongly flag ``alpha`` or ``beta`` too."""
        assert _fields_for(flagged_ir, catalog.MultiProjection) == ["gamma"]
