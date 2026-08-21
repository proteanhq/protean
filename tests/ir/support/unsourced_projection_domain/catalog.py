"""Projector method bodies that exercise the UNSOURCED_PROJECTION_FIELD rule.

Each projection and projector is registered as a real domain by the consuming
test, so a projection name resolves to a *registered* element FQN and a
projector method's construction of it surfaces as a ``ConstructionFact`` on the
projection's FQN, exactly as the fact-catalog corpus does. The write shape each
projector carries, and the branch it drives:

- ``PartialProjector`` constructs ``PartialProjection`` with four of its five
  data fields as keywords, leaving ``city`` unwritten — the positive case, so
  ``city`` is flagged by name.
- ``FullProjector`` covers ``FullProjection``'s ``title`` and ``body`` by
  *attribute* write (``record.title = ...``) rather than construction, and
  leaves ``subtitle`` and ``author`` unwritten, so those two are flagged. This
  pins the attribute-evidence branch to a visible outcome: remove that branch
  and the write set empties, tripping the evidence guard so nothing is flagged
  at all. The two flagged fields also pin emission to sorted field-name order
  (``author`` before ``subtitle``, though declared the other way round).
- ``GuardProjector`` builds its record through a module-level helper the
  analysis cannot follow, so its own methods yield no field write at all — the
  evidence guard, so ``GuardProjection`` is skipped rather than reported.
- ``DynamicProjector`` constructs ``DynamicProjection`` with a ``**kwargs``
  splat (alongside a named field), so the field set is unknowable and the
  projection is disabled — nothing is flagged even though ``second`` is never
  named.
- ``IdentityOnlyProjector`` writes every field of ``IdentityOnlyProjection``
  except its ``identity_field`` (``key``), which the framework fills on write —
  the identity exemption, so nothing is flagged.
- ``MultiProjectorA`` and ``MultiProjectorB`` each cover one of
  ``MultiProjection``'s data fields; coverage is the union of the two, so only
  ``gamma`` (covered by neither) is flagged — a per-projector-instead-of-union
  bug would wrongly flag ``alpha`` or ``beta`` too.
- ``ExternalProjector`` covers only ``tag`` on ``ExternalProjection``, which is
  registered ``externally_populated``. That opt-out skips the projection, so
  ``note`` is not flagged even though no write sources it. Remove the opt-out
  branch and ``note`` would be flagged.
"""

from protean import current_domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.fields import Identifier, String


class Thing(BaseAggregate):
    thing_id = Identifier(identifier=True)
    name = String(max_length=50)


class ThingHappened(BaseEvent):
    thing_id = Identifier(identifier=True)
    name = String(max_length=50)
    email = String(max_length=100)
    status = String(max_length=20)
    region = String(max_length=50)


class OtherHappened(BaseEvent):
    thing_id = Identifier(identifier=True)
    email = String(max_length=100)


# ── Positive: four of five data fields written, the fifth flagged ──────────


class PartialProjection(BaseProjection):
    key = Identifier(identifier=True)
    name = String(max_length=50)
    email = String(max_length=100)
    status = String(max_length=20)
    region = String(max_length=50)
    city = String(max_length=50)


class PartialProjector(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Construct the projection with four fields; ``city`` is never sourced."""
        record = PartialProjection(
            key=event.thing_id,
            name=event.name,
            email=event.email,
            status=event.status,
            region=event.region,
        )
        current_domain.repository_for(PartialProjection).add(record)


# ── Negative: full coverage through attribute writes ──────────────────────


class FullProjection(BaseProjection):
    key = Identifier(identifier=True)
    title = String(max_length=50)
    body = String(max_length=200)
    subtitle = String(max_length=50)
    author = String(max_length=50)


class FullProjector(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Source ``title`` and ``body`` by attribute write, not construction;
        ``subtitle`` and ``author`` stay unwritten and are flagged."""
        record = current_domain.repository_for(FullProjection).get(event.thing_id)
        record.title = event.name
        record.body = event.email
        current_domain.repository_for(FullProjection).add(record)


# ── Negative: no observable writes (the evidence guard) ────────────────────


def _build_guard_record(event: ThingHappened) -> "GuardProjection":
    """A module-level helper the analysis cannot follow: the construction here
    is invisible to ``element_facts(GuardProjector)``."""
    return GuardProjection(key=event.thing_id, label=event.name)


class GuardProjection(BaseProjection):
    key = Identifier(identifier=True)
    label = String(max_length=50)


class GuardProjector(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Build the record through a helper, so this projector's own methods
        write no field the analysis can see."""
        record = _build_guard_record(event)
        current_domain.repository_for(GuardProjection).add(record)


# ── Negative: a dynamic ``**kwargs`` construction disables the check ───────


class DynamicProjection(BaseProjection):
    key = Identifier(identifier=True)
    first = String(max_length=50)
    second = String(max_length=50)


class DynamicProjector(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Construct with a ``**kwargs`` splat alongside a named field, so the
        field set is unknowable and the projection is disabled entirely."""
        data = {"first": event.name, "second": event.email}
        record = DynamicProjection(key=event.thing_id, **data)
        current_domain.repository_for(DynamicProjection).add(record)


# ── Negative: only the identity field is unwritten ─────────────────────────


class IdentityOnlyProjection(BaseProjection):
    key = Identifier(identifier=True)
    caption = String(max_length=50)


class IdentityOnlyProjector(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Write every field except the framework-filled ``key`` identity."""
        record = IdentityOnlyProjection(caption=event.name)
        current_domain.repository_for(IdentityOnlyProjection).add(record)


# ── Union: two projectors cover between them, only the gap is flagged ──────


class MultiProjection(BaseProjection):
    key = Identifier(identifier=True)
    alpha = String(max_length=50)
    beta = String(max_length=50)
    gamma = String(max_length=50)


class MultiProjectorA(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Cover ``alpha`` only; ``beta`` is left to the sibling projector."""
        record = MultiProjection(key=event.thing_id, alpha=event.name)
        current_domain.repository_for(MultiProjection).add(record)


class MultiProjectorB(BaseProjector):
    @on(OtherHappened)
    def on_other_happened(self, event: OtherHappened) -> None:
        """Cover ``beta`` only; the union with ``MultiProjectorA`` leaves only
        ``gamma`` unsourced."""
        record = MultiProjection(key=event.thing_id, beta=event.email)
        current_domain.repository_for(MultiProjection).add(record)


# ── Negative: an externally_populated projection opts out ──────────────────


class ExternalProjection(BaseProjection):
    key = Identifier(identifier=True)
    tag = String(max_length=50)
    note = String(max_length=50)


class ExternalProjector(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Cover ``tag`` only, leaving ``note`` unwritten. The projection is
        registered ``externally_populated``, so the opt-out skips it and ``note``
        is not flagged."""
        record = ExternalProjection(key=event.thing_id, tag=event.name)
        current_domain.repository_for(ExternalProjection).add(record)
