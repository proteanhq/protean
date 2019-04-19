""" Define the interfaces for Repository implementations """
import logging
from abc import ABCMeta
from abc import abstractmethod
from typing import Any

from protean.utils.query import Q

from .resultset import ResultSet

logger = logging.getLogger('protean.repository')


class BaseRepository(metaclass=ABCMeta):
    """Repository interface to interact with databases

    :param conn: A connection/session to the data source of the model
    :param model_cls: The model class registered with this repository
    """

    def __init__(self, provider, entity_cls, model_cls):
        self.provider = provider
        self.conn = self.provider.get_connection()
        self.model_cls = model_cls
        self.entity_cls = entity_cls
        self.schema_name = entity_cls.meta_.schema_name

    @abstractmethod
    def filter(self, criteria: Q, offset: int = 0, limit: int = 10,
               order_by: list = ()) -> ResultSet:
        """
        Filter objects from the repository. Method must return a `ResultSet`
        object
        """

    @abstractmethod
    def create(self, model_obj: Any):
        """Create a new model object from the entity"""

    @abstractmethod
    def update(self, model_obj: Any):
        """Update a model object in the repository and return it"""

    @abstractmethod
    def update_all(self, criteria: Q, *args, **kwargs):
        """Updates object directly in the repository and returns update count"""

    @abstractmethod
    def delete(self):
        """Delete a Record from the Repository"""

    @abstractmethod
    def delete_all(self, criteria: Q = None):
        """Delete a Record from the Repository"""

    @abstractmethod
    def raw(self, query: Any, data: Any = None):
        """Run raw query on Data source.

        Running a raw query on the repository should always returns entity instance objects. If
        the results were not synthesizable back into entity objects, an exception should be thrown.
        """
