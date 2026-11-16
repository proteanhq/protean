"""The DAO Ports: what a database adapter's DAO implements.

A DAO reads and writes one entity class's rows in one database. An adapter's
DAO class subclasses `DAOPort` explicitly and works on database model objects
in the session it is given. It never picks a session and never commits one.
The `DAO` service in `protean.infra.dao` wraps the adapter, supplies the
session, ends a standalone transaction, and builds the entity-level operations
on top.

A provider that declares one of the flags in `_FLAG_PORTS` unlocks an extra
operation. Its DAO class subclasses the Port that goes with the flag, and the
`DAO` service checks that it does when the service is built.
"""

from abc import abstractmethod
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol

from protean.core.entity import BaseEntity
from protean.core.queryset import ResultSet
from protean.port.provider import (
    DatabaseCapabilities,
    DatabaseModelPort,
    ProviderPort,
    SessionProtocol,
)
from protean.utils.query import Q


@dataclass(frozen=True)
class HoldBack:
    """How :meth:`protean.infra.dao.DAO.claim` holds back a row behind earlier
    rows of its group.

    Two rows share a group when both match ``applies``, their ``group_by``
    columns are equal, and both match the same ``lanes`` entry. A grouped row is
    claimable only when every earlier row of its group that matches ``holds``
    is claimed by the same call. Rows that do not match ``applies`` are never
    held and never hold another row.

    Attributes:
        group_by: Column names that must be equal for two rows to share a
            group.
        applies: Rows that take part in grouping. It must require every
            ``group_by`` column to be non-null. Without that, rows with a NULL
            in a ``group_by`` column can share a group on a SQL adapter.
        holds: Rows that still hold their group (for example, every status
            except "published"). It must match every row the claim's criteria
            match, and every row once ``claim_fields`` are applied to it: a row
            that can still be claimed, or is claimed and not finished, holds
            the rows behind it.
        order: Column names, all ascending, that define "earlier" within a
            group. NULL sorts last. The last key must be unique so that the
            order is total.
        lane_of: The same split as ``applies`` and ``lanes``, computed from an
            entity's own values. Returns ``None`` when the row does not match
            ``applies``, else the index of its entry in ``lanes`` (``0`` when
            ``lanes`` is empty).
        lanes: Disjoint ``Q`` objects that together cover every grouped row.
            Rows in different lanes never share a group. Empty means one lane.
    """

    group_by: tuple[str, ...]
    applies: Q
    holds: Q
    order: tuple[str, ...]
    lane_of: Callable[[Any], int | None]
    lanes: tuple[Q, ...] = ()


class DAOPort(Protocol):
    """The storage operations every database adapter's DAO implements.

    Each operation that touches stored rows takes the session to run in as its
    first argument. The adapter runs the operation in that session and leaves
    it open and uncommitted: the caller owns the transaction.

    The adapter DAO class sets the four attributes in its own constructor,
    which takes `(provider, entity_cls, database_model_cls)`. The Protocol
    supplies no constructor body.
    """

    provider: ProviderPort
    entity_cls: type[BaseEntity]
    database_model_cls: type[DatabaseModelPort]
    schema_name: str
    """The table, index or store key the entity's rows live under."""

    def __init__(
        self,
        provider: Any,
        entity_cls: type[BaseEntity],
        database_model_cls: type[DatabaseModelPort],
    ) -> None: ...

    @abstractmethod
    def filter(
        self,
        session: SessionProtocol,
        criteria: Q,
        *,
        offset: int = 0,
        limit: int = 10,
        order_by: Sequence[str] = (),
        with_total: bool = True,
        fields: Sequence[str] | None = None,
    ) -> ResultSet:
        """Return one page of the rows that match ``criteria``.

        Args:
            session: The session to read in.
            criteria: The filter conditions.
            offset: The number of matching rows to skip.
            limit: The most rows to return.
            order_by: Keys to sort by, applied in turn. A ``-`` prefix sorts
                that key descending.
            with_total: When ``False``, the caller does not need the full
                match count. The adapter may skip computing it (for example,
                SQL's separate ``COUNT`` query) and set ``ResultSet.total`` to
                the size of the returned page.
            fields: Column names to fetch, set by ``QuerySet.only()``. The
                identifier is always among them. The adapter fetches only those
                columns. ``None`` fetches full rows.

        Returns:
            A ``ResultSet`` whose ``items`` are raw storage records.
        """

    @abstractmethod
    def count(self, session: SessionProtocol, criteria: Q) -> int:
        """The number of rows that match ``criteria``, read without fetching
        the rows."""

    @abstractmethod
    def insert(self, session: SessionProtocol, model: Any) -> Any:
        """Write ``model`` as a new row and return the model object.

        Raises:
            ValidationError: A unique field's value is already stored, on a
                store that checks unique fields itself.
        """

    @abstractmethod
    def update(
        self,
        session: SessionProtocol,
        model: Any,
        *,
        expected_version: int | None = None,
    ) -> Any:
        """Write ``model`` over its stored row and return the model object.

        When ``expected_version`` is not ``None``, the adapter checks the
        stored version and writes in one atomic step. For example, a SQL
        adapter uses ``UPDATE ... WHERE _version = :expected`` and checks the
        affected row count.

        Raises:
            ObjectNotFoundError: No row is stored under the model's identifier.
            ExpectedVersionError: The stored version is not
                ``expected_version``.
        """

    @abstractmethod
    def update_all(
        self, session: SessionProtocol, criteria: Q, values: Mapping[str, Any]
    ) -> int:
        """Write ``values`` to every row that matches ``criteria``.

        Returns:
            The number of rows that matched ``criteria``.
        """

    @abstractmethod
    def delete(self, session: SessionProtocol, model: Any) -> Any:
        """Delete the row stored under ``model``'s identifier and return the
        model object.

        Raises:
            ObjectNotFoundError: No row is stored under the identifier.
        """

    @abstractmethod
    def delete_all(self, session: SessionProtocol, criteria: Q | None = None) -> int:
        """Delete every row that matches ``criteria``.

        Args:
            session: The session to delete in.
            criteria: The filter conditions. ``None`` deletes every row of the
                table or index.

        Returns:
            The number of rows that matched ``criteria``.
        """

    @abstractmethod
    def has_table(self) -> bool:
        """Whether the table, index or collection exists in the store."""

    def claim_lock(self) -> AbstractContextManager[object]:
        """A lock that the portable claim and the portable bounded delete
        hold while they run.

        This default returns ``contextlib.nullcontext()``, which locks
        nothing. An adapter whose store has no row locks overrides it.
        """
        return nullcontext()


class RawQueryDAOPort(Protocol):
    """A DAO that runs a raw query.

    A DAO class subclasses this port when it implements :meth:`raw`. The
    provider declares ``DatabaseCapabilities.RAW_QUERIES``.
    """

    @abstractmethod
    def raw(self, session: SessionProtocol, query: Any, data: Any = None) -> ResultSet:
        """Run a raw query on the database and return the matching records.

        ``QuerySet.raw()`` calls this through the ``DAO`` service. The query
        bypasses the Unit of Work. Raise an exception when a result cannot be
        turned into a record.

        Args:
            session: The session the service supplies.
            query: The query, passed to the database as it is.
            data: Data to pass along with the query, such as the values for an
                update statement.

        Returns:
            A ``ResultSet`` of the storage records the query returned.
        """


class InsertIfAbsentPort(Protocol):
    """A DAO that writes a row only when no other row holds its unique key.

    A DAO class subclasses this port when it implements both members. The
    provider declares ``DatabaseCapabilities.INSERT_IF_ABSENT``, and
    ``DAO.save_if_absent`` then writes through these members instead of
    checking the key and saving in two steps.

    The unique key is the values of the fields of each ``Index`` the entity
    declares with ``unique=True`` and no ``where`` predicate. Each member makes
    the check and the write one atomic step.
    """

    @abstractmethod
    def insert_if_absent(self, session: SessionProtocol, model: Any) -> bool:
        """Write ``model`` as a new row unless another row holds one of its
        unique keys.

        Returns:
            ``True`` when the row was written, ``False`` when another row holds
            a key. Nothing is written in that case.
        """

    @abstractmethod
    def update_if_absent(
        self,
        session: SessionProtocol,
        model: Any,
        *,
        expected_version: int | None = None,
    ) -> bool:
        """Write ``model`` over its stored row unless another row holds one of
        its unique keys.

        Checks ``expected_version`` as :meth:`DAOPort.update` does.

        Returns:
            ``True`` when the row was written, ``False`` when another row holds
            a key. Nothing is written in that case.
        """


class NativeClaimPort(Protocol):
    """A DAO that claims rows in one statement.

    A DAO class subclasses this port when it implements :meth:`claim`.
    :meth:`protean.infra.dao.DAO.claim` calls it when the provider declares
    ``DatabaseCapabilities.NATIVE_CLAIM``, and calls the portable claim
    otherwise.
    """

    @abstractmethod
    def claim(
        self,
        session: SessionProtocol,
        criteria: Q,
        claim_fields: Mapping[str, Any],
        limit: int,
        order_by: Sequence[str] = (),
        hold_back: HoldBack | None = None,
    ) -> list[Any]:
        """Claim rows with the promises :meth:`protean.infra.dao.DAO.claim`
        states, and return the claimed entities.

        ``limit`` is at least 1.
        """


class ClaimCandidatesPort(Protocol):
    """A DAO that leaves held rows out of a claim's candidate page.

    A DAO class subclasses this port when it implements
    :meth:`claim_candidates`. The portable claim reads its pages through it
    when the provider declares
    ``DatabaseCapabilities.FILTERED_CLAIM_CANDIDATES`` and the claim has a
    ``hold_back``.
    """

    @abstractmethod
    def claim_candidates(
        self,
        session: SessionProtocol,
        criteria: Q,
        limit: int,
        offset: int,
        order_by: Sequence[str],
        hold_back: HoldBack,
    ) -> list[Any]:
        """Read one page of claim candidates.

        Returns up to ``limit`` entities matching ``criteria`` in ``order_by``
        order, skipping the first ``offset``, and leaves out rows that
        ``hold_back`` holds. It must not leave out a row that the claim could
        take.
        """


class BoundedDeletePort(Protocol):
    """A DAO that deletes up to ``limit`` rows in one operation.

    A DAO class subclasses this port when it implements :meth:`delete_top`.
    :meth:`protean.infra.dao.DAO.delete_top` calls it when the provider
    declares ``DatabaseCapabilities.BOUNDED_DELETE``, and calls the portable
    bounded delete otherwise.
    """

    @abstractmethod
    def delete_top(
        self,
        session: SessionProtocol,
        criteria: Q,
        limit: int,
        order_by: str | None = None,
    ) -> int:
        """Delete rows with the promises :meth:`protean.infra.dao.DAO.delete_top`
        states.

        ``limit`` is at least 1.
        """


# The port a DAO class must subclass when its provider declares the flag.
_FLAG_PORTS: dict[DatabaseCapabilities, type[object]] = {
    DatabaseCapabilities.RAW_QUERIES: RawQueryDAOPort,
    DatabaseCapabilities.NATIVE_CLAIM: NativeClaimPort,
    DatabaseCapabilities.FILTERED_CLAIM_CANDIDATES: ClaimCandidatesPort,
    DatabaseCapabilities.BOUNDED_DELETE: BoundedDeletePort,
    DatabaseCapabilities.INSERT_IF_ABSENT: InsertIfAbsentPort,
}


REQUIRED_LOOKUPS: frozenset[str] = frozenset(
    {
        "exact",
        "iexact",
        "contains",
        "icontains",
        "startswith",
        "endswith",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "isnull",
    }
)
"""The lookup names every database provider registers. The provider registry
raises `ConfigurationError` for a provider class that lacks any of them."""


class LookupPort(Protocol):
    """One comparison in a filter, such as `name == "John"`.

    `source` is the left side of the comparison and `target` the right side.
    The SQL and Elasticsearch lookups receive a field name as `source`, and
    the memory lookups receive the stored value of that field.

    How a lookup becomes a query is private to the adapter that runs it. An
    adapter's lookup base class subclasses this Protocol explicitly, and the
    base class constructor sets `source`, `target` and `database_model_cls`.
    The Protocol supplies no constructor body, so a subclass without its own
    constructor builds without these attributes.
    """

    lookup_name: ClassVar[str]
    """The name a filter key uses after `__`, such as `"icontains"`."""

    source: Any
    target: Any
    database_model_cls: type[DatabaseModelPort] | None

    def __init__(
        self,
        source: Any,
        target: Any,
        *,
        database_model_cls: type[DatabaseModelPort] | None = None,
    ) -> None: ...
