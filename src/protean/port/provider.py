"""The database provider Ports: what a database adapter implements.

A provider holds one database's connection settings. It hands out sessions and
DAOs, builds the database model for each entity, and creates and drops the
tables or indices the domain's elements need.
"""

import logging
import pathlib
from abc import abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Flag, auto
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from protean.exceptions import ConfigurationError, NotSupportedError
from protean.port.health import PoolStats
from protean.utils.query import RegisterLookupMixin

if TYPE_CHECKING:
    from protean.core.database_model import BaseDatabaseModel
    from protean.core.entity import BaseEntity
    from protean.core.projection import BaseProjection
    from protean.core.queryset import Record
    from protean.domain import Domain
    from protean.port.dao import LookupPort

logger = logging.getLogger(__name__)


class DatabaseCapabilities(Flag):
    """Capability flags for database providers.

    Individual capabilities are orthogonal -- unlike broker capabilities,
    database capabilities are not strictly hierarchical.  Convenience sets
    bundle common combinations, but individual flags can be mixed freely.
    """

    # Tier 1: Universal Foundation (every provider has these)
    CRUD = auto()  # Create, Read, Update, Delete single records
    FILTER = auto()  # Query/filter records with lookup criteria
    BULK_OPERATIONS = auto()  # update_all(), delete_all()
    ORDERING = auto()  # Server-side ORDER BY support

    # Tier 2: Data Integrity
    TRANSACTIONS = auto()  # Real commit/rollback atomicity
    SIMULATED_TRANSACTIONS = auto()  # In-process commit/rollback, not durable
    OPTIMISTIC_LOCKING = auto()  # Version-based concurrency control

    # Tier 3: Query Power
    RAW_QUERIES = auto()  # Execute raw/native queries

    # Tier 4: Infrastructure
    SCHEMA_MANAGEMENT = auto()  # Create/drop tables/indices
    CONNECTION_POOLING = auto()  # Connection pool management
    SCHEMA_MIGRATIONS = auto()  # Versioned schema changes through a SchemaMigrator

    # Tier 5: Type System
    NATIVE_JSON = auto()  # Native JSON column support
    NATIVE_ARRAY = auto()  # Native array column support

    # Claim and delete
    NATIVE_CLAIM = auto()  # Claims rows in one statement
    BOUNDED_DELETE = auto()  # Deletes up to ``limit`` rows in one operation, without a separate read of their ids
    FILTERED_CLAIM_CANDIDATES = auto()  # Leaves held rows out of a claim's candidates

    # Convenience Capability Sets
    BASIC_STORAGE = CRUD | FILTER | BULK_OPERATIONS | ORDERING

    RELATIONAL = (
        BASIC_STORAGE
        | TRANSACTIONS
        | OPTIMISTIC_LOCKING
        | RAW_QUERIES
        | SCHEMA_MANAGEMENT
        | CONNECTION_POOLING
    )

    DOCUMENT_STORE = BASIC_STORAGE | SCHEMA_MANAGEMENT | OPTIMISTIC_LOCKING

    IN_MEMORY = (
        BASIC_STORAGE | SIMULATED_TRANSACTIONS | OPTIMISTIC_LOCKING | RAW_QUERIES
    )


@runtime_checkable
class SessionProtocol(Protocol):
    """Protocol that database session objects must satisfy.

    Objects returned by ``get_session()`` must implement ``commit``,
    ``rollback``, and ``close``, and expose an ``is_active`` flag.

    Adapters without real transaction support (e.g., Elasticsearch)
    should provide no-op implementations and set ``is_active = True``
    in ``__init__``.

    ``begin()`` is optional, needed only for adapters with deferred
    transaction start (e.g., SQLAlchemy).  The Unit of Work calls
    ``begin()`` only when ``is_active`` is ``False``.
    """

    is_active: bool

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


@runtime_checkable
class SchemaMigrator(Protocol):
    """Protocol that objects returned by ``schema_migrator()`` must satisfy.

    A schema migrator keeps a versioned history of one provider's schema in a
    folder on disk. The ``protean db`` migration commands call it and import
    nothing from the migration tool behind it.
    """

    def init(self, domain_path: str) -> None:
        """Create the migrations folder for ``domain_path``.

        Raises ``ConfigurationError`` when the folder exists and is not empty,
        and leaves it unchanged.
        """

    def migrate(self, message: str) -> pathlib.Path | None:
        """Write a migration from the change between the model and the database.

        Returns the path of the written migration file, or None, and writes no
        file, when the model and the database do not differ.

        Raises ``ConfigurationError`` when the migration tool reports an error.
        """

    def upgrade(self, revision: str = "head", sql: bool = False) -> None:
        """Apply migrations up to ``revision``.

        With ``sql``, print the SQL instead and do not connect to the database.

        Raises ``ConfigurationError`` when the migration tool reports an error.
        """

    def downgrade(self, revision: str, sql: bool = False) -> None:
        """Revert migrations down to ``revision``.

        With ``sql``, print the SQL instead and do not connect to the database.

        Raises ``ConfigurationError`` when the migration tool reports an error.
        """

    def check(self) -> list[str]:
        """Compare the database with the provider's table definitions.

        Returns one line per difference, in the form
        ``<operation> <table>[.<column or index>]``, such as
        ``add_column order.discount``, or an empty list when they agree.
        Writes nothing to the database.

        Raises ``ConfigurationError`` when the database is not at the latest
        migration, when it cannot be read, or when the migration tool reports
        an error.
        """


@dataclass(frozen=True)
class ProviderHealth:
    """What `ProviderPort.health` reports."""

    pool: PoolStats | None
    """The provider's connection pool, or `None` for a provider without one or
    whose pool keeps no counters."""


class DatabaseModelPort(Protocol):
    """The class methods the framework calls on an adapter's database model.

    A DAO converts an entity to a record with `from_entity` on every write,
    and a query converts records back with `to_entity` or `to_records`. Every
    member is a class method, so the framework works with the model class and
    never with an instance of it.

    `BaseDatabaseModel`, the class a user subclasses with
    `@domain.database_model`, satisfies this Protocol structurally.
    """

    @classmethod
    @abstractmethod
    def from_entity(cls, entity: "BaseEntity") -> Any:
        """The storage record for `entity`, ready for the adapter to persist."""

    @classmethod
    @abstractmethod
    def to_entity(cls, item: Any) -> "BaseEntity":
        """The entity or aggregate that the storage record `item` holds."""

    @classmethod
    @abstractmethod
    def to_records(cls, items: list[Any], fields: list[str]) -> "list[Record]":
        """One read-only `Record` per storage record in `items`, in order,
        holding only the attributes named in `fields`."""


class ProviderPort(Protocol):
    """The members every database provider implements.

    An adapter subclasses this, or `RawQueryProviderPort`, explicitly.
    """

    database_type: ClassVar[str]
    """A short identifier for the database, such as `"memory"`,
    `"elasticsearch"` or one of the SQLAlchemy dialect names."""

    name: str
    domain: "Domain"
    config: Mapping[str, Any]

    def __init__(
        self, name: str, domain: "Domain", config: Mapping[str, Any]
    ) -> None: ...

    @property
    @abstractmethod
    def capabilities(self) -> DatabaseCapabilities:
        """The behaviours this provider supports."""

    @abstractmethod
    def get_session(self) -> SessionProtocol:
        """The session the Unit of Work commits or rolls back.

        A backend without transactions returns a session whose methods do
        nothing and whose `is_active` is `True`.
        """

    @abstractmethod
    def get_connection(self) -> object:
        """The adapter's native handle, such as a SQLAlchemy session or an
        Elasticsearch client."""

    @abstractmethod
    def ping(self) -> bool:
        """Whether the database is reachable."""

    @abstractmethod
    def health(self) -> ProviderHealth:
        """The provider's health record."""

    def close(self) -> None:
        """Release the provider's connections and pools. Does nothing by
        default."""
        # mypy treats a Protocol member whose body is only a docstring as
        # abstract, which would make every adapter implement `close`.
        return None  # noqa: RET501

    @abstractmethod
    def clear(self) -> None:
        """Remove every record from the provider's store."""

    def create_schema(self) -> None:
        """Create the tables or indices the domain's elements need, leaving
        existing ones untouched. Does nothing by default."""
        # mypy treats a Protocol member whose body is only a docstring as
        # abstract; a provider without schema objects inherits this no-op.
        return None  # noqa: RET501

    def drop_schema(self) -> None:
        """Drop the tables or indices the domain's elements own. Does nothing
        by default."""
        # mypy treats a Protocol member whose body is only a docstring as
        # abstract; a provider without schema objects inherits this no-op.
        return None  # noqa: RET501

    @abstractmethod
    def dao_for(
        self,
        entity_cls: "type[BaseEntity | BaseProjection]",
        model_cls: "type[DatabaseModelPort]",
    ) -> Any:
        """A DAO for `entity_cls` that stores it through `model_cls`."""

    @abstractmethod
    def model_for(
        self,
        entity_cls: "type[BaseEntity | BaseProjection]",
        model_cls: "type[BaseDatabaseModel] | None" = None,
    ) -> "type[DatabaseModelPort]":
        """The database model class for `entity_cls`.

        With `model_cls`, a user-defined model, it returns a subclass of that
        model with the adapter's internals added, or `model_cls` unchanged when it
        already subclasses the adapter's model class. Without it, it builds a model
        from the entity's fields. The adapter caches each class it builds or
        decorates per entity, and later calls for that entity return the
        cached class.
        """

    @classmethod
    @abstractmethod
    def get_lookups(cls) -> "Mapping[str, type[LookupPort]]":
        """Every lookup class the provider class registers, keyed by lookup
        name."""

    @abstractmethod
    def get_lookup(self, lookup_name: str) -> "type[LookupPort]":
        """The lookup class registered under `lookup_name`.

        Raises `NotImplementedError` naming the lookup and the provider when
        no lookup is registered under `lookup_name`.
        """


class RawQueryProviderPort(ProviderPort, Protocol):
    """The raw-query member, unlocked by `DatabaseCapabilities.RAW_QUERIES`."""

    @abstractmethod
    def raw(self, query: Any, data: Any = None) -> Any:
        """Run `query` on the provider's connection and return the database's
        result unchanged."""


class BaseProvider(RegisterLookupMixin, ProviderPort):
    """Framework logic shared by the built-in providers.

    A provider subclasses this class first and then `ProviderPort`, or
    `RawQueryProviderPort` when it declares `DatabaseCapabilities.RAW_QUERIES`.
    It sets `database_type`, implements the Port's abstract members, and
    registers every lookup in `protean.port.dao.REQUIRED_LOOKUPS`.

    The Custom Database Adapters guide walks through building an adapter: the
    DAO, the database model, lookups, registration, and the call flow.
    """

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Raise `TypeError` when a subclass names `RawQueryProviderPort` but
        defines no `raw` of its own."""
        super().__init_subclass__(**kwargs)
        # `BaseProvider.raw` satisfies the Port's abstract `raw` in the MRO, so
        # without this check such a provider builds and fails at call time.
        if RawQueryProviderPort in cls.__mro__ and cls.raw is BaseProvider.raw:
            raise TypeError(
                f"{cls.__name__} subclasses RawQueryProviderPort but does not "
                "implement raw"
            )

    def __init__(self, name: str, domain: "Domain", config: Mapping[str, Any]) -> None:
        self.name = name
        self.domain = domain
        self.config = config
        self.managed = config.get("managed", True)

    def raw(self, query: Any, data: Any = None) -> Any:
        """Raise `NotSupportedError` naming the provider.

        A provider that declares `DatabaseCapabilities.RAW_QUERIES` overrides
        this with its own `raw`.
        """
        raise NotSupportedError(
            f"Provider '{self.name}' ({self.__class__.__name__}) "
            "does not support raw queries"
        )

    def schema_migrator(self, directory: pathlib.Path) -> SchemaMigrator:
        """Return the schema migrator that keeps its history in ``directory``.

        Raises NotSupportedError if the provider does not declare
        ``SCHEMA_MIGRATIONS``.
        """
        if DatabaseCapabilities.SCHEMA_MIGRATIONS not in self.capabilities:
            raise NotSupportedError(
                f"Provider '{self.name}' ({self.__class__.__name__}) "
                "does not support schema migrations"
            )
        return self._schema_migrator(directory)

    def _schema_migrator(self, directory: pathlib.Path) -> SchemaMigrator:
        """Internal schema migrator factory.

        Override in adapters that declare the SCHEMA_MIGRATIONS capability. The
        default raises NotSupportedError, so an adapter without migrations
        need not implement it.
        """
        raise NotSupportedError(
            f"Provider '{self.name}' ({self.__class__.__name__}) "
            "does not implement schema migrations"
        )

    def owns(self, element_cls: type[Any]) -> bool:
        """Return whether this provider materializes a table/index for ``element_cls``.

        It returns ``False`` for:

        - **Event-sourced aggregates**: They persist to the event store, not a
          database table/index.
        - **Entities of event-sourced aggregates** (at any nesting depth): They
          follow their root aggregate into the event store.
        - **Cache-backed elements** (e.g. ``@domain.projection(cache=...)``):
          They persist to a cache adapter and carry ``meta_.provider is None``.
        - **Elements owned by a different provider**: In multi-provider domains,
          each provider materializes only the elements configured to it.

        Call it after ``domain.init()``, which sets
        ``meta_.aggregate_cluster``.

        Raises:
            ConfigurationError: ``element_cls`` names a provider that is not
                configured.
        """
        meta = element_cls.meta_

        # Event-sourced aggregates (and entities anywhere in their cluster) live
        # in the event store, not a database. Entities inherit their root
        # aggregate via ``aggregate_cluster``; an aggregate is its own cluster.
        # Projections have no cluster, so fall back to the element itself.
        cluster = getattr(meta, "aggregate_cluster", None) or element_cls
        if getattr(cluster.meta_, "is_event_sourced", False):
            return False

        # Cache-backed elements have no database provider (``provider is None``).
        provider_name = getattr(meta, "provider", None)
        if provider_name is None:
            return False

        # A provider name that resolves to nothing is a misconfiguration —
        # surface it here rather than silently skipping the element.
        if provider_name not in self.domain.providers:
            raise ConfigurationError(
                f"{element_cls.__name__} references provider '{provider_name}', "
                f"but no provider is configured with that name"
            )

        # In multi-provider domains, only materialize elements owned by this
        # provider. Provider names are the unique keys of the provider registry,
        # so comparing names resolves ownership without indexing on ``None``.
        return bool(provider_name == self.name)
