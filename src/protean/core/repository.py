"""Abstract Repository Classes"""

import logging

from abc import ABCMeta
from abc import abstractmethod

from math import ceil

from typing import Any


import inflection

from protean.core.entity import Entity
from protean.core.exceptions import ConfigurationError, \
    ObjectNotFoundError
from protean.utils import OptionsMeta

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


class Repository(metaclass=ABCMeta):
    """Repository interface to interact with databases"""

    def __init__(self, db, schema):
        self.db = db
        self.schema = schema
        self.schema_name = schema.__class__.__name__

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

    def __init__(self, meta, schema):
        self.entity = getattr(meta, 'entity', None)
        if not self.entity or not issubclass(self.entity, Entity):
            raise ConfigurationError(
                '`entity` option must be set and be a subclass of `Entity`.')

        # Get the schema name to be used, if not provided default it
        self.schema_name = getattr(meta, 'schema_name', None)
        if not self.schema_name:
            self.schema_name = inflection.underscore(schema.__name__)


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


class RepositoryFactory(metaclass=ABCMeta):
    """Repository Factory interface to retrieve resource repositories"""

    def __init__(self):
        """"Initialize repository factory"""
        self._registry = {}
        self._connection = None

    @abstractmethod
    def get_connection(self):
        """Initialize the repository and return the database object"""

    def register(self, repo: Repository, schema: RepositorySchema):
        """ Register given schema against a repository
        :param repo: The repository to be used for a schema
        :param schema: The schema to be mapped to a repository
        """
        if not issubclass(schema, RepositorySchema):
            raise AssertionError(
                f'Schema {schema} must be subclass of `RepositorySchema`')

        if not issubclass(repo, Repository):
            raise AssertionError(
                f'Repo {repo} must be subclass of `Repository`')

        if schema not in self._registry:
            db = self.get_connection()
            self._registry[schema.__name__] = repo(db, schema())
            logger.debug(
                f'Registered schema {schema.__name__} with repository '
                f'{repo.__name__}.')

    def __getattr__(self, schema):
        try:
            return self._registry[schema]
        except KeyError:
            raise AssertionError('Unregistered Schema')
