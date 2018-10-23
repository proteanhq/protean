""" Define the interfaces for Repository implementations """
import logging

from abc import ABCMeta
from abc import abstractmethod

from typing import Any

import inflection

from protean.core.entity import Entity
from protean.core.exceptions import ConfigurationError, \
    ObjectNotFoundError
from protean.utils import OptionsMeta
from .utils import Pagination

logger = logging.getLogger('protean.repository')


class BaseRepository(metaclass=ABCMeta):
    """Repository interface to interact with databases"""

    def __init__(self, conn, schema_cls):
        self.conn = conn
        self.schema = schema_cls()
        self.schema_name = schema_cls.__name__

    @abstractmethod
    def _create(self, entity: Entity):
        """Create a new Record"""

    def create(self, *args, **kwargs):
        """Create a new Record in the repository"""
        logger.debug(
            f'Creating new {self.schema_name} object using data {kwargs}')

        # Build the entity from the input arguments
        entity = self.schema.opts.entity(*args, **kwargs)

        # Create this object in the repository and return it
        record = self._create(entity)
        return self.schema.to_entity(record)

    @abstractmethod
    def _read(self, page: int = 1, per_page: int = 10, order_by: list = None,
              **filters) -> Pagination:
        """
        Read Record(s) from the repository. Method must return a `Pagination`
        object"""

    def get(self, identifier: Any):
        """Get a specific Record from the Repository
        :param identifier: The id of the record to be fetched from the
        repository.
        """
        logger.debug(
            f'Lookup {self.schema_name} object with identifier {identifier}')
        # Get the ID field for the entity
        entity = self.schema.opts.entity
        filters = {
            entity.id_field: identifier
        }

        # Find this item in the repository or raise Error
        results = self._read(**filters)
        if not results.items:
            raise ObjectNotFoundError(
                f'{self.schema_name} object with identifier {identifier} '
                f'does not exist.')

        # Convert to entity and return it
        return self.schema.to_entity(results.first)

    def filter(self, page: int = 1, per_page: int = 10, order_by: list = (),
               **filters) -> Pagination:
        """
        Read Record(s) from the repository. Method must return a `Pagination`
        object

        :param page: The current page number of the records to be pulled
        :param per_page: The size of each page of the records to be pulled
        :param order_by: The list of parameters to be used for ordering the
        results. Use a `-` before the parameter name to sort in descending
        order and if not ascending order.

        :return Returns a `Pagination` object that holds the filtered results
        """
        logger.debug(
            f'Query {self.schema_name} objects with filters {filters} and '
            f'order results by {order_by}')

        # order_by clause must be list of keys
        if order_by and not isinstance(order_by, list):
            order_by = [order_by]

        # Call the read method of the repository
        results = self._read(page, per_page, order_by, **filters)

        # Convert the returned results to entity and return it
        entity_items = []
        for item in results.items:
            entity_items.append(self.schema.to_entity(item))
        results.items = entity_items

        return results

    @abstractmethod
    def _update(self, entity: Entity):
        """Update a Record in the repository and return it"""

    def update(self, identifier: Any, data: dict):
        """Update a Record in the repository

        :param identifier: The id of the record to be updated
        :param data: A dictionary of record properties to be updated
        """
        logger.debug(
            f'Updating existing {self.schema_name} object with id {identifier} '
            f'using data {data}')

        # Get the entity and update it
        entity = self.get(identifier)
        entity.update(data)

        # Update the record and return the Entity
        record = self._update(entity)
        return self.schema.to_entity(record)

    @abstractmethod
    def delete(self, identifier: Any):
        """Delete a Record from the Repository"""


class RepositorySchemaOpts(object):
    """class Meta options for the :class:`RepositorySchema`."""

    def __init__(self, meta, schema_cls):
        self.entity = getattr(meta, 'entity', None)
        if not self.entity or not issubclass(self.entity, Entity):
            raise ConfigurationError(
                '`entity` option must be set and be a subclass of `Entity`.')

        # Get the schema name to be used, if not provided default it
        self.schema_name = getattr(meta, 'schema_name', None)
        if not self.schema_name:
            self.schema_name = inflection.underscore(schema_cls.__name__)

        # Get the database bound to this schema
        self.bind = getattr(meta, 'bind', 'default')


class RepositorySchema(metaclass=OptionsMeta):
    """ Repository Schema defines an index/table in the repository"""
    options_class = RepositorySchemaOpts
    opts = None

    @property
    def name(self):
        """ Return the name of the schema"""
        return self.opts.schema_name

    @abstractmethod
    def from_entity(self, entity):
        """Initialize Repository Schema object from Entity object"""

    @abstractmethod
    def to_entity(self, *args, **kwargs):
        """Convert Repository Schema Object to Entity Object"""


class BaseConnectionHandler(metaclass=ABCMeta):
    """ Interface to manage connections to the database """
    @abstractmethod
    def get_connection(self):
        """ Get the connection object for the repository"""
