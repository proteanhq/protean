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
    build exercises every branch: the four-of-five positive, attribute-write
    evidence, the empty-evidence guard, a dynamic ``**kwargs`` construction, the
    identity exemption, the two-projector union, the ``externally_populated``
    opt-out, a fully sourced projection, a write on a handler parameter, a
    delete, a bulk update, a write delegated to a helper, a write on an
    unrelated object, and a projector the index cannot resolve.
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
        catalog.CompleteProjection,
        catalog.ReceiverProjection,
        catalog.DeleteProjection,
        catalog.BulkProjection,
        catalog.HelperProjection,
        catalog.UnrelatedProjection,
        catalog.NoSourceProjection,
    ):
        domain.register(projection)
    domain.register(catalog.ExternalProjection, externally_populated=True)
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
    domain.register(
        catalog.ExternalProjector,
        projector_for=catalog.ExternalProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.CompleteProjector,
        projector_for=catalog.CompleteProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.ReceiverProjector,
        projector_for=catalog.ReceiverProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.DeleteProjector,
        projector_for=catalog.DeleteProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.BulkProjector,
        projector_for=catalog.BulkProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.HelperProjector,
        projector_for=catalog.HelperProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.UnrelatedProjector,
        projector_for=catalog.UnrelatedProjection,
        aggregates=[catalog.Thing],
    )
    domain.register(
        catalog.NoSourceProjector,
        projector_for=catalog.NoSourceProjection,
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

    def test_attribute_write_sources_only_written_fields(self, flagged_ir):
        """``FullProjector`` attribute-writes ``title`` and ``body`` and nothing
        else, so the attribute-evidence branch sources exactly those two and the
        unwritten ``subtitle`` and ``author`` are flagged. Emission is in sorted
        field-name order (``author`` before ``subtitle``), and if the attribute
        branch were removed the write set would empty and the evidence guard
        would flag nothing instead, so this pins the branch to a visible
        outcome."""
        assert _fields_for(flagged_ir, catalog.FullProjection) == [
            "author",
            "subtitle",
        ]

    def test_externally_populated_projection_opts_out(self, flagged_ir):
        """``ExternalProjection`` is registered ``externally_populated``, so the
        opt-out skips it: ``note`` is unwritten yet not flagged. Without the
        opt-out branch, ``note`` would be flagged."""
        assert fqn(catalog.ExternalProjection) in flagged_ir["projections"]
        assert _fields_for(flagged_ir, catalog.ExternalProjection) == []

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

    def test_fully_sourced_projection_flags_nothing(self, flagged_ir):
        """``CompleteProjector`` names every non-identity field of
        ``CompleteProjection``, so the projection produces no finding. This is
        the all-covered negative: unlike the identity-only case it does not lean
        on the identity exemption, so a rule that emitted for a sourced field
        would fail here."""
        assert fqn(catalog.CompleteProjection) in flagged_ir["projections"]
        assert _fields_for(flagged_ir, catalog.CompleteProjection) == []

    def test_a_write_on_a_handler_parameter_is_not_evidence(self, flagged_ir):
        """``ReceiverProjector`` assigns ``byline`` on ``self``, a parameter of
        the handler, so the write is provably not a write to the record.
        ``headline`` is sourced by construction, so the evidence guard does not
        trip and ``byline`` is reported. Count every ``is_write`` fact and
        ``byline`` disappears from this list."""
        assert _fields_for(flagged_ir, catalog.ReceiverProjection) == ["byline"]

    def test_a_delete_is_not_evidence(self, flagged_ir):
        """``DeleteProjector`` stores ``kept`` and deletes ``marker``. Both are
        ``is_write`` attribute facts, so a rule that reads ``is_write`` alone
        would treat the delete as sourcing ``marker``; only ``kept`` fills a
        value, so ``marker`` is flagged and ``kept`` is not."""
        assert _fields_for(flagged_ir, catalog.DeleteProjection) == ["marker"]

    def test_a_bulk_update_is_neither_evidence_nor_a_disabler(self, flagged_ir):
        """``BulkProjector`` names ``first`` in a construction, then bulk-updates
        through ``update(**changes)``. A call fact carries only the callee name,
        so that ``update`` is indistinguishable from ``dict.update`` and cannot
        be tied to this projection. Reading it as a write to the projection would
        disable the check here, and would let any ``mapping.update(**changes)``
        in any projector method blind the rule; the unnamed ``second`` is flagged
        instead."""
        assert _fields_for(flagged_ir, catalog.BulkProjection) == ["second"]

    def test_a_helper_parameter_write_is_evidence(self, flagged_ir):
        """``HelperProjector`` delegates its ``headline`` write to
        ``_apply(self, record, event)``, where the record is the helper's own
        parameter. The handler parameter exclusion must not reach a helper, or
        ``headline`` is reported alongside the genuinely unwritten ``byline``."""
        assert _fields_for(flagged_ir, catalog.HelperProjection) == ["byline"]

    def test_a_write_on_an_unrelated_object_is_not_evidence(self, flagged_ir):
        """``UnrelatedProjector`` builds its record through a helper the analysis
        cannot follow, and its only visible write is ``trail`` on a plain object.
        ``trail`` names no field of this projection, so it is not evidence and
        does not clear the evidence guard: count it and ``label`` is reported off
        a write that has nothing to do with the projection."""
        assert fqn(catalog.UnrelatedProjection) in flagged_ir["projections"]
        assert _fields_for(flagged_ir, catalog.UnrelatedProjection) == []

    def test_an_unresolvable_projector_fails_open(self, flagged_ir):
        """``NoSourceProjector`` is built by ``type()``, so the element index
        finds no class body for it. The rule skips it instead of raising, which
        leaves the projection with no observed write, so nothing is flagged and
        the build still completes."""
        assert fqn(catalog.NoSourceProjection) in flagged_ir["projections"]
        assert _fields_for(flagged_ir, catalog.NoSourceProjection) == []
