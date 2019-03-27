"""Base class for Providers"""

import uuid
from abc import ABCMeta
from abc import abstractmethod

from protean.utils.query import RegisterLookupMixin


class BaseProvider(RegisterLookupMixin, metaclass=ABCMeta):
    """Provider Implementation for each database that acts as a gateway to configure the database,
    retrieve connections and perform commits
    """

    def __init__(self, conn_info: dict):
        """Initialize Provider with Connection/Adapter details"""
        self.identifier = str(uuid.uuid4())
        self.conn_info = conn_info

    def _extract_lookup(self, key):
        """Extract lookup method based on key name format"""
        parts = key.split('__')
        # 'exact' is the default lookup if there was no explicit comparison op in `key`
        #   Assume there is only one `__` in the key.
        #   FIXME Change for child attribute query support
        op = 'exact' if len(parts) == 1 else parts[1]

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
        """ Get the connection object for the repository"""

    @abstractmethod
    def close_connection(self, conn):
        """ Close the connection object for the repository"""

    @abstractmethod
    def get_repository(self, model_cls):
        """ Return a repository object configured with a live connection"""

    def get_model(self, model_cls):
        """ Return the fully baked model, with any additions necessary

        This is a placeholder method that can be overridden in each provider
        """
        return model_cls
