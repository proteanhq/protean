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
- ``CompleteProjector`` names every non-identity field of
  ``CompleteProjection``, so a fully sourced projection produces no finding at
  all — the negative that fails if the rule ever emits for a covered field.
- ``ReceiverProjector`` assigns ``byline`` on its own ``self``, a parameter of
  the handler and so provably not the record. That write is not evidence, so
  ``byline`` stays flagged even though the name matches.
- ``DeleteProjector`` writes ``kept`` and only ever deletes ``marker``. A
  ``del`` unbinds the attribute rather than filling it, so ``marker`` stays
  flagged.
- ``BulkProjector`` names ``first`` in a construction and then bulk-updates
  through ``update(**changes)``, whose field set is unknowable. That disables
  ``BulkProjection`` the way a dynamic construction does, so ``second`` is not
  flagged.
- ``NoSourceProjector`` is assembled by ``type()``, so the element index cannot
  find a class body for it and answers ``None``. The rule fails open on that,
  skipping the projector rather than raising, so ``NoSourceProjection`` is
  reported on nothing.
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


# ── Negative: every non-identity field sourced ────────────────────────────


class CompleteProjection(BaseProjection):
    key = Identifier(identifier=True)
    headline = String(max_length=50)
    summary = String(max_length=200)


class CompleteProjector(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Name every non-identity field, so the projection is fully sourced and
        nothing is flagged."""
        record = CompleteProjection(
            key=event.thing_id,
            headline=event.name,
            summary=event.email,
        )
        current_domain.repository_for(CompleteProjection).add(record)


# ── Negative: a write on a parameter is not a write to the record ─────────


class ReceiverProjection(BaseProjection):
    key = Identifier(identifier=True)
    headline = String(max_length=50)
    byline = String(max_length=50)


class ReceiverProjector(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Source ``headline`` on the record, and stash ``byline`` on the
        projector itself. ``self`` is a parameter of this handler, so that write
        is provably not a write to the record and ``byline`` stays flagged."""
        self.byline = event.name
        record = ReceiverProjection(key=event.thing_id, headline=event.name)
        current_domain.repository_for(ReceiverProjection).add(record)


# ── Negative: a delete unbinds a field, it does not fill one ──────────────


class DeleteProjection(BaseProjection):
    key = Identifier(identifier=True)
    kept = String(max_length=50)
    marker = String(max_length=50)


class DeleteProjector(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Write ``kept`` and clear ``marker``. Both are ``is_write`` attribute
        facts, but only the store fills a value, so ``marker`` stays flagged."""
        record = current_domain.repository_for(DeleteProjection).get(event.thing_id)
        record.kept = event.name
        del record.marker
        current_domain.repository_for(DeleteProjection).add(record)


# ── Negative: a dynamic bulk update disables the check ────────────────────


class BulkProjection(BaseProjection):
    key = Identifier(identifier=True)
    first = String(max_length=50)
    second = String(max_length=50)


class BulkProjector(BaseProjector):
    @on(ThingHappened)
    def on_thing_happened(self, event: ThingHappened) -> None:
        """Name ``first`` in a construction, then bulk-update through a
        ``**kwargs`` splat. Which fields that update fills is unknowable, so the
        projection is disabled and ``second`` is not flagged."""
        repository = current_domain.repository_for(BulkProjection)
        record = BulkProjection(key=event.thing_id, first=event.name)
        repository.add(record)
        changes = {"second": event.email}
        repository._dao.query.filter(key=event.thing_id).update(**changes)


# ── Negative: a projector the element index cannot resolve ────────────────


class NoSourceProjection(BaseProjection):
    key = Identifier(identifier=True)
    label = String(max_length=50)
    extra = String(max_length=50)


def _no_source_handler(self, event: ThingHappened) -> None:
    """``NoSourceProjector``'s handler body, written as a module-level function
    so the class below can be assembled without a class body."""
    record = NoSourceProjection(key=event.thing_id, label=event.name)
    current_domain.repository_for(NoSourceProjection).add(record)


#: Built by ``type()``, so this module's source carries no
#: ``class NoSourceProjector`` for the element index to find and
#: ``element_class_entry`` answers ``None``. The rule has to fail open there —
#: skip the projector rather than raise — which leaves ``NoSourceProjection``
#: with no observed write and so reported on nothing, ``extra`` included.
NoSourceProjector = type(
    "NoSourceProjector",
    (BaseProjector,),
    {"on_thing_happened": on(ThingHappened)(_no_source_handler)},
)
