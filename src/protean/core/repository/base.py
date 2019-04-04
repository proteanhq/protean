""" Define the interfaces for Repository implementations """
import logging
from abc import ABCMeta
from abc import abstractmethod
from typing import Any

from protean.utils.query import Q

from .pagination import Pagination

logger = logging.getLogger('protean.repository')


class BaseRepository(metaclass=ABCMeta):
    """Repository interface to interact with databases

    :param conn: A connection/session to the data source of the model
    :param model_cls: The model class registered with this repository
    """

    def __init__(self, provider, model_cls):
        self.provider = provider
        self.conn = self.provider.get_connection()
        self.model_cls = model_cls
        self.entity_cls = model_cls.opts_.entity_cls
        self.model_name = model_cls.opts_.model_name

    @abstractmethod
    def _filter_objects(self, criteria: Q, page: int = 1, per_page: int = 10,
                        order_by: list = ()) -> Pagination:
        """
        Filter objects from the repository. Method must return a `Pagination`
        object
        """

    @abstractmethod
    def _create_object(self, model_obj: Any):
        """Create a new model object from the entity"""

    @abstractmethod
    def _update_object(self, model_obj: Any):
        """Update a model object in the repository and return it"""

    @abstractmethod
    def _update_all_objects(self, criteria: Q, *args, **kwargs):
        """Updates object directly in the repository and returns update count"""

    @abstractmethod
    def _delete_object(self):
        """Delete a Record from the Repository"""

    @abstractmethod
    def _delete_all_objects(self, criteria: Q):
        """Delete a Record from the Repository"""
