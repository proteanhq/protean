"""Unit of Work tracking for the `DAO` service.

A Unit of Work holds one instance of each aggregate it loads (ADR-0046).
The first load of an aggregate in a Unit of Work syncs the aggregate's
``_event_position`` from the event store and registers it in the Unit of
Work's identity map. A second load in the same Unit of Work returns the
tracked instance in place of the new copy. Only ``add()`` makes a tracked
aggregate's events commit with the Unit of Work.

`track` and `tracked_instance` take the `DAO` first. A `DAO` that works
outside the Unit of Work (`DAO.is_standalone`) tracks nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from protean.core.aggregate import BaseAggregate
from protean.utils import DomainObjects
from protean.utils.globals import current_domain, current_uow
from protean.utils.reflection import id_field

if TYPE_CHECKING:
    from protean.core.entity import BaseEntity
    from protean.infra.dao import DAO


def sync_event_position(entity: BaseEntity) -> None:
    """Set an aggregate's ``_event_position`` to the position of the last
    event written to its stream, so expected-version checks on later
    ``raise_()`` calls count from the store.

    It changes nothing for a non-aggregate entity, or for an aggregate whose
    stream holds no event.
    """
    if entity.element_type != DomainObjects.AGGREGATE:
        return

    id_f = id_field(entity)
    assert id_f is not None and id_f.field_name is not None
    identifier = getattr(entity, id_f.field_name)
    store = current_domain.event_store
    last_message = store.read_last_message(
        f"{entity.meta_.stream_category}-{identifier}"
    )
    if last_message:
        assert last_message.metadata is not None
        assert last_message.metadata.event_store is not None
        entity._event_position = last_message.metadata.event_store.position


def track(dao: DAO, entity: BaseEntity) -> BaseEntity:
    """Return the instance to hand back for an entity ``dao`` just loaded.

    For an aggregate the active Unit of Work already tracks, it returns the
    tracked instance. Two copies of one aggregate in one transaction would
    each count versions and event positions from the store, which has not
    seen the other copy's pending changes.

    Otherwise it syncs the aggregate's event position and, when ``dao``
    works inside a Unit of Work, registers the aggregate there and returns
    it. It returns a non-aggregate entity unchanged.
    """
    if not isinstance(entity, BaseAggregate):
        return entity

    tracked = tracked_instance(dao, entity)
    if tracked is not None:
        return tracked

    sync_event_position(entity)
    if not dao.is_standalone:
        current_uow._add_to_identity_map(entity)
    return entity


def tracked_instance(dao: DAO, entity: BaseEntity) -> BaseAggregate | None:
    """Return the instance of ``entity``'s aggregate that the active Unit of
    Work tracks.

    It returns ``None`` when ``dao`` works outside a Unit of Work, when
    ``entity`` is not an aggregate, or when the Unit of Work tracks no
    instance of it.
    """
    if dao.is_standalone or not isinstance(entity, BaseAggregate):
        return None
    id_f = id_field(entity)
    assert id_f is not None and id_f.field_name is not None
    return current_uow._tracked_instance(type(entity), getattr(entity, id_f.field_name))
