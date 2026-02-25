"""Base class for Providers"""

from abc import ABCMeta, abstractmethod
from enum import Flag, auto
from typing import Any

from protean.utils.query import RegisterLookupMixin


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
    SIMULATED_TRANSACTIONS = auto()  # Copy-on-write UoW semantics (no true rollback)
    OPTIMISTIC_LOCKING = auto()  # Version-based concurrency control

    # Tier 3: Query Power
    RAW_QUERIES = auto()  # Execute raw/native queries

    # Tier 4: Infrastructure
    SCHEMA_MANAGEMENT = auto()  # Create/drop tables/indices
    CONNECTION_POOLING = auto()  # Connection pool management

    # Tier 5: Type System
    NATIVE_JSON = auto()  # Native JSON column support
    NATIVE_ARRAY = auto()  # Native array column support

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


class BaseProvider(RegisterLookupMixin, metaclass=ABCMeta):
    """Provider Implementation for each database that acts as a gateway to configure the database,
    retrieve connections and perform commits
    """

    def __init__(self, name, domain, conn_info: dict):
        """Initialize Provider with Connection/Adapter details"""
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

    @property
    @abstractmethod
    def capabilities(self) -> DatabaseCapabilities:
        """Return the capabilities of this database provider."""

    def has_capability(self, capability: DatabaseCapabilities) -> bool:
        """Check if provider has a specific capability."""
        return capability in self.capabilities

    def has_all_capabilities(self, capabilities: DatabaseCapabilities) -> bool:
        """Check if provider has all the specified capabilities."""
        return (self.capabilities & capabilities) == capabilities

    def has_any_capability(self, capabilities: DatabaseCapabilities) -> bool:
        """Check if provider has any of the specified capabilities."""
        return bool(self.capabilities & capabilities)

    def _extract_lookup(self, key):
        """Extract lookup method based on key name format"""
        parts = key.split("__")
        # 'exact' is the default lookup if there was no explicit comparison op in `key`
        #   Assume there is only one `__` in the key.
        #   FIXME Change for child attribute query support
        op = "exact" if len(parts) == 1 else parts[1]

        # Construct and assign the lookup class as a filter criteria
        return parts[0], self.get_lookup(op)

    @abstractmethod
    def get_session(self):
        """Establish a new session with the database.

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
    def get_connection(self):
        """Get the connection object for the repository"""

    @abstractmethod
    def is_alive(self) -> bool:
        """Check if the connection is alive"""

    @abstractmethod
    def close(self):
        """Close the provider and clean up any persistent connections or resources.

        This method should be called to properly dispose of connections and free up
        resources when the provider is no longer needed. Implementations should:
        - Close any connection pools
        - Dispose of any persistent connections
        - Clean up any other resources (engines, clients, etc.)
        """

    @abstractmethod
    def get_dao(self, entity_cls, database_model_cls):
        """Return a DAO object configured with a live connection"""

    @abstractmethod
    def decorate_database_model_class(self, entity_cls, database_model_cls):
        """Return decorated Model Class for custom-defined models"""

    @abstractmethod
    def construct_database_model_class(self, entity_cls):
        """Return dynamically constructed Model Class"""

    @abstractmethod
    def raw(self, query: Any, data: Any = None):
        """Run raw query directly on the database

        Query should be executed immediately on the database as a separate unit of work
            (in a different transaction context). The results should be returned as returned by
            the database without any intervention. It is left to the consumer to interpret and
            organize the results correctly.
        """

    @abstractmethod
    def _data_reset(self) -> None:
        """Flush all data in the provider's persistence store.

        Useful for clearing data between tests.
        """

    @abstractmethod
    def _create_database_artifacts(self) -> None:
        """Create tables, indices, or other storage structures.

        Should be idempotent — existing structures are left untouched.
        """

    @abstractmethod
    def _drop_database_artifacts(self) -> None:
        """Drop all tables, indices, or storage structures."""
