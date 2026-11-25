"""The read path of the `DAO` service.

Each function takes the `DAO` as its first argument and reads its entity
class's rows in the session `DAO.session_scope` picks. Rows become entities
after the ``session_scope`` block exits: each entity is marked retrieved and,
inside a Unit of Work, each aggregate is tracked in it. A read with ``fields``
set returns read-only `Record` objects and tracks nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

from protean.exceptions import (
    NotSupportedError,
    ObjectNotFoundError,
    TooManyObjectsError,
)
from protean.port.dao import RawQueryDAOPort
from protean.port.database import DatabaseCapabilities
from protean.utils.query import Q
from protean.utils.reflection import id_field

if TYPE_CHECKING:
    from protean.core.entity import BaseEntity
    from protean.core.queryset import ResultSet
    from protean.infra.dao import DAO

logger = logging.getLogger(__name__)


def _to_entities(dao: DAO, items: list[Any]) -> list[BaseEntity]:
    """Convert model rows to entities, marked retrieved, with each aggregate
    swapped for the instance the Unit of Work already tracks, if any."""
    entities = []
    for item in items:
        entity = dao.database_model_cls.to_entity(item)
        entity.state_.mark_retrieved()
        entities.append(dao.track(entity))
    return entities


def fetch(
    dao: DAO,
    criteria: Q,
    *,
    offset: int = 0,
    limit: int = 10,
    order_by: Sequence[str] = (),
    with_total: bool = True,
    fields: list[str] | None = None,
) -> ResultSet:
    """Return one page of the entities that match ``criteria``.

    With ``fields`` set, ``items`` holds read-only `Record` objects with
    those fields, and nothing is tracked in the Unit of Work. An empty
    ``fields`` selects nothing, as ``QuerySet.only()`` with no names does. With
    ``with_total`` set to ``False``, the adapter may skip computing
    ``total``.
    """
    # An empty selection means full entities, as in ``QuerySet.only()``.
    fields = fields or None
    with dao.session_scope() as session:
        results = dao._adapter.filter(
            session,
            criteria,
            offset=offset,
            limit=limit,
            order_by=order_by,
            with_total=with_total,
            fields=fields,
        )

    if fields is not None:
        results.items = dao.database_model_cls.to_records(results.items, fields)
    else:
        results.items = _to_entities(dao, results.items)
    return results


def count(dao: DAO, criteria: Q) -> int:
    """Return the number of rows that match ``criteria``."""
    with dao.session_scope() as session:
        return dao._adapter.count(session, criteria)


def raw(dao: DAO, query: Any, data: Any = None) -> ResultSet:
    """Run ``query`` through the adapter's ``raw`` and return the entities.

    Raises:
        NotSupportedError: The provider does not declare ``RAW_QUERIES``.
    """
    provider = dao.provider
    if DatabaseCapabilities.RAW_QUERIES not in provider.capabilities:
        raise NotSupportedError(
            f"Provider '{provider.name}' ({provider.__class__.__name__}) "
            "does not support raw queries"
        )

    with dao.session_scope() as session:
        results = cast(RawQueryDAOPort, dao._adapter).raw(session, query, data)

    results.items = _to_entities(dao, results.items)
    return results


def get(dao: DAO, identifier: Any) -> BaseEntity:
    """Return the one entity whose identity is ``identifier``.

    Raises:
        ObjectNotFoundError: No entity has the identifier.
        TooManyObjectsError: More than one entity has the identifier.
    """
    logger.debug(
        f"Lookup `{dao.entity_cls.__name__}` object with identifier {identifier}"
    )

    # Filter on the ID field of the entity
    entity_id_field = id_field(dao.entity_cls)
    assert entity_id_field is not None, (
        f"`{dao.entity_cls.__name__}` does not have an identity field"
    )
    assert entity_id_field.field_name is not None
    filters = {
        entity_id_field.field_name: identifier,
    }

    results = dao.query.filter(**filters).all()
    if not results:
        raise ObjectNotFoundError(
            f"`{dao.entity_cls.__name__}` object with identifier {identifier} "
            f"does not exist."
        )

    if len(results) > 1:
        raise TooManyObjectsError(
            f"More than one object of `{dao.entity_cls.__name__}` exist with identifier {identifier}",
        )

    # Return the first result, because `filter` would have returned an array
    result: BaseEntity | None = results.first
    assert result is not None
    return result


def find_by(dao: DAO, **kwargs: Any) -> BaseEntity:
    """Return the one entity whose attributes equal ``kwargs``.

    Raises:
        ObjectNotFoundError: No entity matches.
        TooManyObjectsError: More than one entity matches.
    """
    logger.debug(f"Lookup `{dao.entity_cls.__name__}` object with values {kwargs}")

    # Filter for item in the data store
    results = dao.query.filter(**kwargs).all()

    if not results:
        raise ObjectNotFoundError(
            f"`{dao.entity_cls.__name__}` object with values {list(kwargs.items())} "
            f"does not exist."
        )

    if len(results) > 1:
        raise TooManyObjectsError(
            f"More than one object of `{dao.entity_cls.__name__}` exist "
            f"with values {list(kwargs.items())}",
        )

    # Return the first result, because `filter` would have returned an array
    result: BaseEntity | None = results.first
    assert result is not None
    return result


def exists(dao: DAO, excludes_: dict[str, Any], **filters: Any) -> bool:
    """Return whether any entity matches ``filters`` and none of
    ``excludes_``."""
    results = dao.query.filter(**filters).exclude(**excludes_)

    # Invokes the __bool__ method on `ResultSet`.
    return bool(results)
