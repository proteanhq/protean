"""Base class for Providers"""

from abc import ABCMeta, abstractmethod
from typing import Any

from protean.utils.query import RegisterLookupMixin


class BaseProvider(RegisterLookupMixin, metaclass=ABCMeta):
    """Provider Implementation for each database that acts as a gateway to configure the database,
    retrieve connections and perform commits
    """

    def __init__(self, name, domain, conn_info: dict):
        """Initialize Provider with Connection/Adapter details"""
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

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
    def get_dao(self, entity_cls, model_cls):
        """Return a DAO object configured with a live connection"""

    @abstractmethod
    def decorate_model_class(self, entity_cls, model_cls):
        """Return decorated Model Class for custom-defined models"""

    @abstractmethod
    def construct_model_class(self, entity_cls):
        """Return dynamically constructed Model Class"""

    @abstractmethod
    def raw(self, query: Any, data: Any = None):
        """Run raw query directly on the database

        Query should be executed immediately on the database as a separate unit of work
            (in a different transaction context). The results should be returned as returned by
            the database without any intervention. It is left to the consumer to interpret and
            organize the results correctly.
        """
