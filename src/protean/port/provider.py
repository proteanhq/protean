"""Base class for Providers"""

import logging
import pathlib
from abc import ABCMeta, abstractmethod
from enum import Flag, auto
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from protean.exceptions import ConfigurationError, NotSupportedError
from protean.utils.query import RegisterLookupMixin

if TYPE_CHECKING:
    from protean.port.dao import BaseLookup

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

    Objects returned by ``get_session()`` and ``get_connection()`` must
    implement ``commit``, ``rollback``, and ``close``, and expose an
    ``is_active`` flag.

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


class BaseProvider(RegisterLookupMixin, metaclass=ABCMeta):
    """Base class for database providers.

    A provider holds one database's connection settings. It hands out sessions
    and DAOs, builds the database model for each entity, and creates and drops
    the tables or indices the domain's elements need.

    A subclass sets ``__database__``, implements every abstract method and the
    ``capabilities`` property, and registers every lookup in
    ``REQUIRED_LOOKUPS``. ``get_session()`` and ``get_connection()`` return
    objects that satisfy ``SessionProtocol``. A backend without transactions
    returns a session whose methods do nothing and whose ``is_active`` is
    ``True``.

    The Custom Database Adapters guide walks through building an adapter: the
    DAO, the database model, lookups, registration, and the call flow.
    """

    # Short database identifier every concrete provider must set (e.g.
    # ``"memory"``, ``"elasticsearch"``, or one of the SQLAlchemy dialect
    # values). Declared here so the adapter contract is visible to both type
    # checkers; concrete providers assign it as a class attribute.
    __database__: ClassVar[str]

    # Minimum lookups every adapter must register
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

    def __init__(self, name: str, domain: Any, conn_info: dict[str, Any]) -> None:
        """Initialize Provider with Connection/Adapter details"""
        self.name = name
        self.domain = domain
        self.conn_info = conn_info
        self.managed = conn_info.get("managed", True)

    @property
    @abstractmethod
    def capabilities(self) -> DatabaseCapabilities:
        """Return the capabilities of this database provider."""

    @classmethod
    def validate_lookups(cls) -> list[str]:
        """Check that all required lookups are registered.

        Returns a list of missing lookup names. Empty list means
        all required lookups are present.
        """
        registered = set(cls.get_lookups().keys())
        return sorted(cls.REQUIRED_LOOKUPS - registered)

    def _extract_lookup(self, key: str) -> "tuple[str, type[BaseLookup]]":
        """Extract lookup method based on key name format"""
        parts = key.split("__")
        # 'exact' is the default lookup if there was no explicit comparison op in `key`
        # Only single-level field__op lookups are supported.  Nested attribute
        # queries (e.g. address__city__contains) are unnecessary because:
        #   - Value objects are flattened into shadow fields (billing_address_street)
        #   - Child entities live in separate repositories with their own queries
        op = "exact" if len(parts) == 1 else parts[1]

        # Construct and assign the lookup class as a filter criteria
        return parts[0], self.get_lookup(op)

    @abstractmethod
    def get_session(self) -> SessionProtocol:
        """Establish a new session with the database.

        Must return an object satisfying `SessionProtocol`.

        Typically the session factory should be created once per application. Which is then
        held on to and passed to different transactions.

        In Protean's case, the session scope and the transaction scope match. Which means that a
        new session is created when a transaction needs to be initiated (at the beginning of
        request handling, for example) and terminated (after committing or rolling back) at the end
        of the process. The session will be used as a component in Unit of Work Pattern, to handle
        transactions reliably.

        Sessions are made available to requests as part of a Context Manager.
        """

    @abstractmethod
    def get_connection(self) -> Any:
        """Get the connection object for the repository.

        Must return an object satisfying `SessionProtocol`.
        """

    @abstractmethod
    def is_alive(self) -> bool:
        """Check if the connection is alive"""

    @abstractmethod
    def close(self) -> None:
        """Close the provider and clean up any persistent connections or resources.

        This method should be called to properly dispose of connections and free up
        resources when the provider is no longer needed. Implementations should:

        - Close any connection pools
        - Dispose of any persistent connections
        - Clean up any other resources (engines, clients, etc.)
        """

    @abstractmethod
    def get_dao(self, entity_cls: type[Any], database_model_cls: type[Any]) -> Any:
        """Return a DAO object configured with a live connection"""

    @abstractmethod
    def decorate_database_model_class(
        self, entity_cls: type[Any], database_model_cls: type[Any]
    ) -> type[Any]:
        """Enhance a user-defined DatabaseModel class with adapter internals.

        Called when the user has defined a custom ``@domain.model`` for an
        entity. The model class is passed in, so add adapter-specific base
        classes, column mappings, or metadata as needed.

        Must return the decorated model class.
        """

    @abstractmethod
    def construct_database_model_class(self, entity_cls: type[Any]) -> type[Any]:
        """Dynamically build a DatabaseModel class for an entity.

        Called when no user-defined ``@domain.model`` exists for the entity.
        The framework calls this during domain initialization for every
        aggregate/entity that doesn't have an explicit model mapping.

        Must return a class that extends ``BaseDatabaseModel`` with
        ``from_entity()`` and ``to_entity()`` implemented.
        """

    def raw(self, query: Any, data: Any = None) -> Any:
        """Run raw query directly on the database.

        Query should be executed immediately on the database as a separate unit of work
            (in a different transaction context). The results should be returned as returned by
            the database without any intervention. It is left to the consumer to interpret and
            organize the results correctly.

        Raises NotSupportedError if the provider does not support raw queries.
        """
        if DatabaseCapabilities.RAW_QUERIES not in self.capabilities:
            raise NotSupportedError(
                f"Provider '{self.name}' ({self.__class__.__name__}) "
                "does not support raw queries"
            )
        return self._raw(query, data)

    @abstractmethod
    def _raw(self, query: Any, data: Any = None) -> Any:
        """Internal raw query implementation.

        Override in adapters that support RAW_QUERIES capability.
        Adapters without RAW_QUERIES need not provide a meaningful implementation
        as the base class gates access via ``raw()``.
        """

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

    def pool_stats(self) -> dict[str, int]:
        """Return connection pool statistics.

        Providers that support connection pooling should override this to
        return a dict with keys ``size``, ``checked_out``, ``overflow``,
        and ``checked_in``.  The default implementation returns an empty
        dict, signalling that no pool metrics are available.
        """
        return {}

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

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all data in the provider's persistence store.

        Useful for clearing data between tests.
        """

    @abstractmethod
    def _create_database_artifacts(self) -> None:
        """Create tables, indices, or other storage structures.

        Should be idempotent: existing structures are left untouched.
        """

    @abstractmethod
    def _drop_database_artifacts(self) -> None:
        """Drop all tables, indices, or storage structures."""
