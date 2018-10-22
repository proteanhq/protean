"""Abstract Repository Classes"""

import logging
import importlib

from abc import ABCMeta
from abc import abstractmethod

from math import ceil

from typing import Any


import inflection

from protean.core.entity import Entity
from protean.core.exceptions import ConfigurationError, \
    ObjectNotFoundError
from protean.utils import OptionsMeta
from protean.conf import active_config

logger = logging.getLogger('protean.repository')


class Pagination(object):
    """Internal helper class returned by :meth:`Repository._read`
    """

    def __init__(self, page: int, per_page: int, total: int,
                 items: list):
        # the current page number (1 indexed)
        self.page = page
        # the number of items to be displayed on a page.
        self.per_page = per_page
        # the total number of items matching the query
        self.total = total
        # the items for the current page
        self.items = items

    @property
    def pages(self):
        """The total number of pages"""
        if self.per_page == 0 or self.total is None:
            pages = 0
        else:
            pages = int(ceil(self.total / float(self.per_page)))

        return pages

    @property
    def has_prev(self):
        """True if a previous page exists"""
        return self.page > 1

    @property
    def has_next(self):
        """True if a next page exists."""
        return self.page < self.pages

    @property
    def first(self):
        """Return the first item from the result"""
        if self.items:
            return self.items[0]
        else:
            return None


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


class RepositoryFactory:
    """Repository Factory interface to retrieve resource repositories"""

    def __init__(self):
        """"Initialize repository factory"""
        self._registry = {}
        self._connections = {}
        self._repositories = None

    @property
    def repositories(self):
        """ Return the databases configured for the application"""
        if self._repositories is None:
            self._repositories = active_config.REPOSITORIES

        if not isinstance(self._repositories, dict) or self._repositories == {}:
            raise ConfigurationError(
                "'REPOSITORIES' config must be a dict and at least one "
                "database must be defined")

        if 'default' not in self._repositories:
            raise ConfigurationError(
                "You must define a 'default' repository")

        return self._repositories

    def register(self, schema_cls, repo_cls=None):
        """ Register the given schema with the factory
        :param schema_cls: class of the schema to be registered
        :param repo_cls: Optional repository class to use if not the
        `Repository` defined by the provider is userd
        """
        if not issubclass(schema_cls, RepositorySchema):
            raise AssertionError(
                f'Schema {schema_cls} must be subclass of `RepositorySchema`')

        if repo_cls and not issubclass(repo_cls, BaseRepository):
            raise AssertionError(
                f'Repository {repo_cls} must be subclass of `BaseRepository`')

        # Register the schema if it does not exist
        schema_name = schema_cls.__name__
        if schema_name not in self._registry:
            # Lookup the connection details for the schema
            try:
                conn_info = self.repositories[schema_cls.opts.bind]
            except KeyError:
                raise ConfigurationError(
                    f"'{schema_cls.opts.bind}' repository not found in "
                    f"'REPOSITORIES'")

            # Load the repository provider
            provider = importlib.import_module(conn_info['PROVIDER'])

            # If no connection exists then build it
            if schema_cls.opts.bind not in self._connections:
                conn_handler = provider.ConnectionHandler(conn_info)
                self._connections[schema_cls.opts.bind] = \
                    conn_handler.get_connection()

            # Finally register the schema against the provider repository
            repo_cls = repo_cls or provider.Repository
            self._registry[schema_name] = repo_cls(
                self._connections[schema_cls.opts.bind], schema_cls)
            logger.debug(
                f'Registered schema {schema_name} with repository provider '
                f'{conn_info["PROVIDER"]}.')

    def __getattr__(self, schema):
        try:
            return self._registry[schema]
        except KeyError:
            raise AssertionError('Unregistered Schema')


rf = RepositoryFactory()
