"""The write path of the `DAO` service.

Each function that reads or writes storage takes the `DAO` as its first
argument and writes its entity class's rows in the session
`DAO.session_scope` picks. The helpers that work only on an entity, a model
object or an entity class take those and no `DAO`. The path keeps these
guarantees:

- Optimistic concurrency. A save of a persisted aggregate passes the version
  it was loaded at to the adapter's ``update``, which raises
  `ExpectedVersionError` when the stored version differs. A failed save of a
  persisted aggregate puts ``_version`` back; a failed first save leaves it
  advanced. ``_next_version`` advances once the write commits: at once for a
  standalone save, and on commit inside a Unit of Work.
- Unit of Work. Inside a Unit of Work nothing commits until the Unit of Work
  does, and a saved aggregate enters its identity map as saved. A pending
  ``Auto(increment=True)`` key is flushed and copied back onto the entity
  before the save returns.
- Pre-persist hooks. ``auto_now`` and ``auto_now_add`` stamping runs first,
  then the domain's aggregate enrichers, which skip the framework's internal
  aggregates. A hook that raises, or breaks an invariant, has its writes
  undone and aborts the save, and its ``ValidationError`` names the hook in
  ``location``. ``apply_hooks=False`` skips both.
- Uniqueness. A create checks every unique field that holds a value; a
  field that is ``None`` or empty is skipped. A save of a persisted
  entity checks none. The deprecated ``update`` checks them and leaves out
  the entity's own identifier.
"""

from __future__ import annotations

import datetime
import logging
import operator
from collections.abc import Iterator
from contextlib import contextmanager
from functools import reduce
from typing import TYPE_CHECKING, Any, cast, get_args

from protean.core.aggregate import BaseAggregate, _pre_persist_change
from protean.core.index import Index
from protean.exceptions import ObjectNotFoundError, ValidationError
from protean.port.dao import InsertIfAbsentPort
from protean.port.database import DatabaseCapabilities, DatabaseModelPort
from protean.utils import DomainObjects, _callable_qualname
from protean.utils.globals import _domain_now, current_domain, current_uow
from protean.utils.query import Q
from protean.utils.reflection import declared_fields, fields, id_field, unique_fields

if TYPE_CHECKING:
    from protean.core.entity import BaseEntity
    from protean.fields.base import Field
    from protean.infra.dao import DAO

# The write path logs under the service's logger name.
logger = logging.getLogger("protean.infra.dao")


def _lifecycle_timestamp_fields(
    entity_obj: Any, *, is_create: bool
) -> dict[str, Field]:
    """Return the ``auto_now`` / ``auto_now_add`` fields this save stamps.

    Django-parity semantics: ``auto_now`` fields are stamped on every save;
    ``auto_now_add`` fields only on the initial (create) save.
    """
    return {
        name: field_obj
        for name, field_obj in fields(entity_obj).items()
        if getattr(field_obj, "auto_now", False)
        or (is_create and getattr(field_obj, "auto_now_add", False))
    }


def _stamp_lifecycle_timestamps(entity_obj: Any, to_stamp: dict[str, Field]) -> None:
    """Set each DateTime/Date field in ``to_stamp`` to the current time.

    A single ``now``, read from the domain's injectable clock (so frozen-clock
    tests apply), is shared across all stamped fields on this entity.
    """
    now = _domain_now()
    for name, field_obj in to_stamp.items():
        # ``_python_type`` may be Optional-wrapped (auto_now fields are not
        # required); unwrap to the underlying date/datetime to pick the value.
        base_type: Any = getattr(field_obj, "_python_type", None)
        base_type = next(
            (a for a in get_args(base_type) if a is not type(None)), base_type
        )
        value: datetime.date | datetime.datetime = (
            now.date() if base_type is datetime.date else now
        )
        setattr(entity_obj, name, value)


@contextmanager
def _pre_persist_hook(
    entity_obj: Any, location: str, *, writes_only_to_self: bool = False
) -> Iterator[None]:
    """Run one pre-persist hook's writes on ``entity_obj``.

    When the object belongs to an aggregate, the writes run in a
    ``_pre_persist_change`` block on the aggregate root. A projection, or an
    entity saved on its own, has no aggregate to check, so its writes run as
    they are. Inside a caller's own ``atomic_change`` block the aggregate may
    be mid-change, so the block only undoes a raising hook's writes and leaves
    the checks to the caller's block. That block checks the final state on its
    exit and undoes the in-memory changes if it fails, but a save made inside
    it has already written its row.
    """
    root = getattr(entity_obj, "_root", None) or entity_obj
    if not isinstance(root, BaseAggregate):
        yield
        return

    writes_only = entity_obj if writes_only_to_self else None
    with _pre_persist_change(
        root,
        location,
        writes_only=writes_only,
        defer_checks=root._disable_invariant_checks,
    ):
        yield


def _unique_key_indexes(entity_cls: type[BaseEntity]) -> list[Index]:
    """``entity_cls``'s ``Index`` declarations with ``unique=True`` and no
    ``where`` predicate. Their fields make up the entity's unique keys."""
    return [
        index
        for index in getattr(entity_cls.meta_, "indexes", ()) or ()
        if isinstance(index, Index) and index.unique and index.where is None
    ]


def _stored_value(
    database_model_cls: type[DatabaseModelPort], model_obj: Any, name: str
) -> Any:
    """The value ``model_obj`` stores under ``name``.

    Reads it through the model class's ``_get_value()`` when the model defines
    one, and reads an attribute otherwise.
    """
    # ``_get_value`` is not a ``DatabaseModelPort`` member, but every
    # ``BaseDatabaseModel`` has it and adapters override it for dict records.
    get_value = getattr(database_model_cls, "_get_value", None)
    if get_value is not None:
        return get_value(model_obj, name)
    return getattr(model_obj, name)


def _key_values(
    entity_cls: type[BaseEntity],
    database_model_cls: type[DatabaseModelPort],
    model_obj: Any,
    index: Index,
) -> dict[str, Any] | None:
    """``model_obj``'s values for ``index``'s fields, keyed by the name each
    field is stored under, or ``None`` when any value is ``None``."""
    entity_fields = fields(entity_cls)
    values = {}
    for name in index.fields:
        field_obj = entity_fields.get(name)
        # An index names either a field or the attribute it is stored under,
        # and a filter matches stored names.
        stored_name = getattr(field_obj, "attribute_name", None) or name
        values[stored_name] = _stored_value(database_model_cls, model_obj, stored_name)
    if any(value is None for value in values.values()):
        return None
    return values


def _unique_key_criteria(
    entity_cls: type[BaseEntity],
    database_model_cls: type[DatabaseModelPort],
    model_obj: Any,
) -> Q | None:
    """Match the other rows that share a unique key with ``model_obj``.

    A unique key is the values of the fields of one of
    :func:`_unique_key_indexes`. A key with a ``None`` among its values is
    left out, and the result is ``None`` when no key is left. The row stored
    under ``model_obj``'s own identifier never matches.
    """
    groups = [
        Q(**values)
        for index in _unique_key_indexes(entity_cls)
        if (values := _key_values(entity_cls, database_model_cls, model_obj, index))
        is not None
    ]
    if not groups:
        return None

    criteria = reduce(operator.or_, groups)
    id_f = id_field(entity_cls)
    assert id_f is not None and id_f.field_name is not None
    id_attr = id_f.attribute_name or id_f.field_name
    identifier = _stored_value(database_model_cls, model_obj, id_attr)
    return criteria & ~Q(**{id_attr: identifier})


def _log_save_failure(exc: Exception) -> None:
    location = getattr(exc, "location", None)
    logger.error(
        f"Failed saving entity because {exc}"
        + (f" (at {location})" if location else "")
    )


class _UniqueKeyTaken(Exception):
    """An ``InsertIfAbsentPort`` member wrote nothing, because another row
    holds a unique key of the entity being saved."""


def _is_pending_auto_field(entity_obj: Any, field_name: str, field_obj: Any) -> bool:
    """True if ``field_obj`` is an ``Auto(increment=True)`` field whose value
    on ``entity_obj`` has not been generated yet (still ``None``).

    A caller-supplied value is thus never treated as pending, so it is
    neither flushed-for nor overwritten during reflection.
    """
    return getattr(field_obj, "increment", False) and (
        getattr(entity_obj, field_name) is None
    )


def _has_pending_auto_field(entity_obj: Any) -> bool:
    """Return True if the entity has any ``Auto(increment=True)`` field still
    awaiting a store-generated value.

    Used to decide whether a pre-reflection flush is worth its cost: a
    relational adapter assigns such a value only when the INSERT is flushed.
    Entities identified by a client-supplied value (e.g. the common
    UUID/string identifier) have no pending auto field and skip the flush.
    """
    return any(
        _is_pending_auto_field(entity_obj, field_name, field_obj)
        for field_name, field_obj in declared_fields(entity_obj).items()
    )


def _reflect_auto_fields(entity_obj: Any, model_obj: Any) -> None:
    """Copy store-generated auto-increment values back onto the entity.

    An ``Auto(increment=True)`` field's value is produced by the
    persistence store during the create, not by the entity. After the
    record is created, reflect that value back onto the in-memory instance
    so the caller holds the same identity that was persisted. Only fields
    still unset on the entity are updated, so a caller-supplied value is
    never overwritten.
    """
    for field_name, field_obj in declared_fields(entity_obj).items():
        if _is_pending_auto_field(entity_obj, field_name, field_obj):
            if isinstance(model_obj, dict):
                # The memory model dict is keyed by field name.
                field_val = model_obj[field_name]
            else:
                # An object model (SQLAlchemy) exposes the generated column
                # under its attribute name, which differs from the field
                # name when ``referenced_as`` is set.
                attribute_name = field_obj.attribute_name
                assert attribute_name is not None
                field_val = getattr(model_obj, attribute_name)

            setattr(entity_obj, field_name, field_val)


def create(dao: DAO, *args: Any, **kwargs: Any) -> BaseEntity:
    """Build an entity from ``args`` and ``kwargs``, check its unique fields
    and write it as a new row."""
    logger.debug(f"Creating new `{dao.entity_cls.__name__}` object using data {kwargs}")

    try:
        # Build the entity from input arguments
        # Raises validation errors, if any, at this point
        entity_obj = dao.entity_cls(*args, **kwargs)

        # Check unique fields, write the row and reflect auto-increment
        # values. Raises validation errors if unique constraints are violated.
        _write_insert(dao, entity_obj, if_absent=False)

        # Set Entity status to saved to let everybody know it has been persisted
        entity_obj.state_.mark_saved()

        # Track aggregate at the UoW level, to be able to perform actions on UoW commit,
        #   like persisting events raised by the aggregate.
        if current_uow and entity_obj.element_type == DomainObjects.AGGREGATE:
            current_uow._add_to_identity_map(entity_obj, saved=True)

        return entity_obj
    except ValidationError as exc:
        logger.error(f"Failed creating entity because of {exc}")
        raise


def _validate_and_update_version(entity_obj: Any) -> int | None:
    """Compute the expected version and advance the entity's version.

    Returns the expected version that the persistence store must match
    atomically during the adapter's subsequent ``update()`` call, or ``None``
    for new (unpersisted) entities.
    """
    expected_version: int | None = None

    if entity_obj.state_.is_persisted:
        expected_version = entity_obj._version

    # Advance to the next version: the model built from this entity
    # carries it for the write. ``_next_version`` moves on only once the
    # write is committed (see ``_save`` and ``UnitOfWork.commit``).
    entity_obj._version = entity_obj._next_version

    return expected_version


def apply_pre_persist_hooks(dao: DAO, entity_obj: Any) -> None:
    """Stamp ``auto_now``/``auto_now_add`` fields, then run aggregate
    enrichers, as `DAO.apply_pre_persist_hooks` states."""
    is_create = not entity_obj.state_.is_persisted
    stamped = _lifecycle_timestamp_fields(entity_obj, is_create=is_create)
    if stamped:
        location = (
            f"auto_now stamping of {', '.join(stamped)} "
            f"on {type(entity_obj).__qualname__}"
        )
        with _pre_persist_hook(entity_obj, location, writes_only_to_self=True):
            _stamp_lifecycle_timestamps(entity_obj, stamped)
    if (
        entity_obj.element_type == DomainObjects.AGGREGATE
        and current_domain
        and current_domain._aggregate_enrichers
        and not current_domain._domain_registry.is_internal(dao.entity_cls)
    ):
        for enricher in current_domain._aggregate_enrichers:
            location = (
                f"aggregate enricher {_callable_qualname(enricher)} "
                f"on {type(entity_obj).__qualname__}"
            )
            with _pre_persist_hook(entity_obj, location):
                enricher(entity_obj)


def save(dao: DAO, entity_obj: Any, *, apply_hooks: bool = True) -> Any:
    """Persist ``entity_obj`` as `DAO.save` states."""
    return _save(dao, entity_obj, apply_hooks=apply_hooks, if_absent=False)


def _save(dao: DAO, entity_obj: Any, *, apply_hooks: bool, if_absent: bool) -> Any:
    """Persist ``entity_obj`` as `DAO.save` states.

    With ``if_absent``, the adapter's ``InsertIfAbsentPort`` members write
    the row, and :class:`_UniqueKeyTaken` is raised when another row holds
    a unique key of the entity.
    """
    logger.debug(f"Saving `{dao.entity_cls.__name__}` object")

    expected_version: int | None = None
    if entity_obj.element_type == DomainObjects.AGGREGATE:
        expected_version = _validate_and_update_version(entity_obj)

    try:
        # Pre-persist hooks run while the entity is still a live object,
        # before ``from_entity`` freezes it into a model. auto_now stamps
        # run first, then registered enrichers (so an enricher may override
        # a stamped timestamp). Both fire on create and update; a raised
        # enricher aborts the save (the version advance is rolled back for an
        # update in the ``except`` below). The call goes through the DAO
        # method, so a patch of `DAO.apply_pre_persist_hooks` applies here.
        if apply_hooks:
            dao.apply_pre_persist_hooks(entity_obj)

        if entity_obj.state_.is_persisted:
            _write_update(dao, entity_obj, expected_version, if_absent)
        else:
            _write_insert(dao, entity_obj, if_absent)

        # Set Entity status to saved to let everybody know it has been persisted
        entity_obj.state_.mark_saved()

        # A standalone write is already committed, so match what a reload
        # would give. Under a UoW the commit advances ``_next_version``
        # instead: until then, events raised on this instance belong to
        # the version this transaction writes.
        if dao._is_standalone and entity_obj.element_type == DomainObjects.AGGREGATE:
            entity_obj._next_version = entity_obj._version + 1

        # Track aggregate at the UoW level, to be able to perform actions on UoW commit,
        #   like persisting events raised by the aggregate.
        if current_uow and entity_obj.element_type == DomainObjects.AGGREGATE:
            # The element may have changed from the time it was loaded or may have been
            #   updated multiple times. We retain the last copy in seen.
            current_uow._add_to_identity_map(entity_obj, saved=True)

        return entity_obj
    except Exception as exc:
        # Roll back the version advance so the entity stays consistent
        # with the persistence store after a failed save.
        if expected_version is not None:
            entity_obj._version = expected_version
        # ``save_if_absent`` logs a ``ValidationError`` only when it
        # re-raises it, because a taken unique key turns it into ``None``.
        if not isinstance(exc, _UniqueKeyTaken) and not (
            if_absent and isinstance(exc, ValidationError)
        ):
            _log_save_failure(exc)
        raise


def _write_insert(dao: DAO, entity_obj: Any, if_absent: bool) -> None:
    """Check ``entity_obj``'s unique fields, write it as a new row, and
    copy store-generated auto-increment values back onto it.

    Raises:
        ValidationError: A unique field's value is taken.
        _UniqueKeyTaken: With ``if_absent``, another row holds a unique
            key of the entity.
    """
    # Perform unique checks. Raises validation errors if unique constraints are violated.
    _validate_unique(dao, entity_obj)

    model_obj = dao.database_model_cls.from_entity(entity_obj)
    with dao.session_scope() as session:
        if if_absent:
            adapter = cast(InsertIfAbsentPort, dao._adapter)
            if not adapter.insert_if_absent(session, model_obj):
                raise _UniqueKeyTaken
        else:
            model_obj = dao._adapter.insert(session, model_obj)

        # A relational adapter assigns an Auto(increment=True) key only
        # when the INSERT is flushed; under a UoW that flush is deferred
        # to commit, after add() has returned. Force it here so the value
        # materializes before we reflect it. A standalone session is
        # committed (and flushed) when the scope ends, so this is UoW-only,
        # and it is skipped entirely when no auto field is pending (the
        # common client-supplied identifier).
        if not dao._is_standalone and _has_pending_auto_field(entity_obj):
            dao.provider.flush(session)

    # Reflect store-generated auto-increment values back onto the
    # entity so an Auto(increment=True) field is populated after add().
    _reflect_auto_fields(entity_obj, model_obj)


def _write_update(
    dao: DAO, entity_obj: Any, expected_version: int | None, if_absent: bool
) -> None:
    """Write ``entity_obj``'s values to its stored row.

    Raises:
        ExpectedVersionError: The stored version differs from
            ``expected_version``.
        _UniqueKeyTaken: With ``if_absent``, another row holds a unique
            key of the entity.
    """
    model_obj = dao.database_model_cls.from_entity(entity_obj)
    with dao.session_scope() as session:
        if not if_absent:
            dao._adapter.update(session, model_obj, expected_version=expected_version)
            return

        adapter = cast(InsertIfAbsentPort, dao._adapter)
        if not adapter.update_if_absent(
            session, model_obj, expected_version=expected_version
        ):
            raise _UniqueKeyTaken


def save_if_absent(dao: DAO, entity_obj: Any, *, apply_hooks: bool = True) -> Any:
    """Save ``entity_obj`` unless another row already holds its unique key,
    as `DAO.save_if_absent` states."""
    if DatabaseCapabilities.INSERT_IF_ABSENT not in dao.provider.capabilities:
        return _save_if_key_free(dao, entity_obj, apply_hooks=apply_hooks)

    version = (
        entity_obj._version
        if entity_obj.element_type == DomainObjects.AGGREGATE
        else None
    )
    with dao._adapter.claim_lock():
        try:
            return _save(dao, entity_obj, apply_hooks=apply_hooks, if_absent=True)
        except _UniqueKeyTaken:
            pass
        except ValidationError as exc:
            if not _unique_key_taken(dao, entity_obj):
                _log_save_failure(exc)
                raise
        # ``_save`` raises before it marks the entity saved or tracks it
        # in the Unit of Work, so only the version advance is left to undo.
        if version is not None:
            entity_obj._version = version
        return None


def _save_if_key_free(dao: DAO, entity_obj: Any, *, apply_hooks: bool) -> Any:
    """Check for ``entity_obj``'s unique key, then save it when no other
    row holds the key. Returns ``None`` when one does."""
    if _unique_key_taken(dao, entity_obj):
        return None
    return dao.save(entity_obj, apply_hooks=apply_hooks)


def _unique_key_taken(dao: DAO, entity_obj: Any) -> bool:
    """Whether another stored row shares a unique key with ``entity_obj``."""
    # The values as the store holds them: the model ``from_entity`` builds
    # applies a ``Reference``'s identifier, a serialized ``Custom`` field,
    # stored names and any transform a custom database model adds.
    criteria = _unique_key_criteria(
        dao.entity_cls,
        dao.database_model_cls,
        dao.database_model_cls.from_entity(entity_obj),
    )
    return criteria is not None and dao.count(criteria) > 0


def _apply_update(
    dao: DAO,
    entity_obj: Any,
    *data: Any,
    apply_hooks: bool = True,
    **kwargs: Any,
) -> BaseEntity:
    """Apply a field patch to an existing entity and persist it, as
    `DAO.update` states."""
    logger.debug(
        f"Updating existing `{dao.entity_cls.__name__}` object with id {entity_obj.id}"
    )

    if not entity_obj.state_.is_persisted:
        raise ObjectNotFoundError(
            f"`{dao.entity_cls.__name__}` object with identifier {entity_obj.id} "
            f"does not exist."
        )

    entity_obj._update_data(*data, **kwargs)
    # ``save`` skips the uniqueness check on its update branch, so run it here
    # before delegating the persist (version advance, timestamps, enrichers).
    _validate_unique(dao, entity_obj, create=False)
    updated: BaseEntity = dao.save(entity_obj, apply_hooks=apply_hooks)
    return updated


def _validate_unique(dao: DAO, entity_obj: Any, create: bool = True) -> None:
    """Validate the unique constraints for the entity. Raise ValidationError, if constraints were violated.

    This method internally uses each field object's fail method to construct a valid error message.

    :param entity_obj: Entity object to be validated
    :param create: boolean value to indicate that the validation is part of a create operation
    """
    # Build the filters from the unique constraints
    filters, excludes = {}, {}

    # Construct filter criteria based on unique fields defined in Entity class
    for field_name, field_obj in unique_fields(dao.entity_cls).items():
        lookup_value = getattr(entity_obj, field_name, None)

        # Ignore empty lookup values
        if lookup_value in (None, "", [], (), {}):
            continue

        # Ignore identifiers on updates
        if not create and field_obj.identifier:
            excludes[field_name] = lookup_value
            continue

        filters[field_name] = lookup_value

    # Lookup the objects by filters and raise error if objects exist
    for filter_key, lookup_value in filters.items():
        if dao.exists(excludes, **{filter_key: lookup_value}):
            field_obj = declared_fields(dao.entity_cls)[filter_key]
            field_obj.fail(
                "unique",
                entity_name=dao.entity_cls.__name__,
                field_name=filter_key,
                value=lookup_value,
            )


def delete(dao: DAO, entity_obj: Any) -> Any:
    """Delete ``entity_obj``'s row, unless it is already destroyed, and mark
    it destroyed. Returns ``entity_obj``."""
    try:
        if not entity_obj.state_.is_destroyed:
            model_obj = dao.database_model_cls.from_entity(entity_obj)
            with dao.session_scope() as session:
                dao._adapter.delete(session, model_obj)

            # Set Entity status to destroyed to let everybody know the object is no longer referable
            entity_obj.state_.mark_destroyed()

        return entity_obj
    except Exception as exc:  # logs any delete failure, then re-raises
        logger.error(f"Failed entity deletion because of {exc}")
        raise


def delete_all(dao: DAO, criteria: Q | None = None) -> int:
    """Delete every row that matches ``criteria``, or every row when
    ``criteria`` is ``None``, and return the number deleted."""
    try:
        with dao.session_scope() as session:
            return dao._adapter.delete_all(session, criteria)
    except Exception as exc:
        logger.error(f"Failed deletion of all records because of {exc}")
        raise
