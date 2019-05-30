""" Define the interfaces for Repository implementations """
# Standard Library Imports
import logging

from abc import ABCMeta, abstractmethod
from typing import Any

# Protean
from protean.core.entity import BaseEntity
from protean.core.exceptions import ObjectNotFoundError, ValidationError
from protean.core.field.basic import Auto, Field
from protean.core.queryset import QuerySet
from protean.utils.query import Q

# Local/Relative Imports
from .resultset import ResultSet

logger = logging.getLogger('protean.repository')


class BaseDAO(metaclass=ABCMeta):
    """Repository interface to interact with databases

    :param conn: A connection/session to the data source of the model
    :param model_cls: The model class registered with this repository
    """

    def __init__(self, domain, provider, entity_cls, model_cls):
        self.domain = domain
        self.provider = provider
        self.conn = self.provider.get_connection()
        self.model_cls = model_cls
        self.entity_cls = entity_cls
        self.query = QuerySet(domain, self.entity_cls)
        self.schema_name = entity_cls.meta_.schema_name

    ###############################
    # Repository-specific methods #
    ###############################

    @abstractmethod
    def _filter(self, criteria: Q, offset: int = 0, limit: int = 10,
                order_by: list = ()) -> ResultSet:
        """
        Filter objects from the repository. Method must return a `ResultSet`
        object
        """

    @abstractmethod
    def _create(self, model_obj: Any):
        """Create a new model object from the entity"""

    @abstractmethod
    def _update(self, model_obj: Any):
        """Update a model object in the repository and return it"""

    @abstractmethod
    def _update_all(self, criteria: Q, *args, **kwargs):
        """Updates object directly in the repository and returns update count"""

    @abstractmethod
    def _delete(self):
        """Delete a Record from the Repository"""

    @abstractmethod
    def _delete_all(self, criteria: Q = None):
        """Delete a Record from the Repository"""

    @abstractmethod
    def _raw(self, query: Any, data: Any = None):
        """Run raw query on Data source.

        Running a raw query on the repository should always returns entity instance objects. If
        the results were not synthesizable back into entity objects, an exception should be thrown.
        """

    ######################
    # Life-cycle methods #
    ######################

    def get(self, identifier: Any) -> BaseEntity:
        """Get a specific Record from the Repository

        :param identifier: id of the record to be fetched from the repository.
        """
        logger.debug(f'Lookup `{self.entity_cls.__name__}` object with identifier {identifier}')
        # Get the ID field for the entity
        filters = {
            self.entity_cls.meta_.id_field.field_name: identifier
        }

        # Find this item in the repository or raise Error
        results = self.query.filter(**filters).limit(1).all()
        if not results:
            raise ObjectNotFoundError(
                f'`{self.entity_cls.__name__}` object with identifier {identifier} '
                f'does not exist.')

        # Return the first result
        return results.first

    def find_by(self, **kwargs) -> 'BaseEntity':
        """Find a specific entity record that matches one or more criteria.

        :param kwargs: named arguments consisting of attr_name and attr_value pairs to search on
        """
        logger.debug(f'Lookup `{self.entity_cls.__name__}` object with values '
                     f'{kwargs}')

        # Find this item in the repository or raise Error
        results = self.query.filter(**kwargs).limit(1).all()

        if not results:
            raise ObjectNotFoundError(
                f'`{self.entity_cls.__name__}` object with values {[item for item in kwargs.items()]} '
                f'does not exist.')

        # Return the first result
        return results.first

    def exists(self, excludes_, **filters):
        """ Return `True` if objects matching the provided filters and excludes
        exist if not return false.

        Calls the `filter` method by default, but can be overridden for better and
            quicker implementations that may be supported by a database.

        :param excludes_: entities without this combination of field name and
            values will be returned
        """
        results = self.query.filter(**filters).exclude(**excludes_)
        return bool(results)

    def create(self, *args, **kwargs) -> 'BaseEntity':
        """Create a new record in the repository.

        Also performs unique validations before creating the entity

        :param args: positional arguments for the entity
        :param kwargs: keyword arguments for the entity
        """
        logger.debug(
            f'Creating new `{self.entity_cls.__name__}` object using data {kwargs}')

        try:
            # Build the entity from the input arguments
            # Raises validation errors, if any, at this point
            entity_obj = self.entity_cls(*args, **kwargs)

            # Do unique checks, create this object and return it
            self._validate_unique(entity_obj)

            # Build the model object and create it
            model_obj = self._create(self.model_cls.from_entity(entity_obj))

            # Update the auto fields of the entity
            for field_name, field_obj in entity_obj.meta_.declared_fields.items():
                if isinstance(field_obj, Auto):
                    if isinstance(model_obj, dict):
                        field_val = model_obj[field_name]
                    else:
                        field_val = getattr(model_obj, field_name)
                    setattr(entity_obj, field_name, field_val)

            # Set Entity status to saved
            entity_obj.state_.mark_saved()

            return entity_obj
        except ValidationError:
            # FIXME Log Exception
            raise

    def save(self, entity_obj):
        """Save a new Entity into repository.

        Performs unique validations before creating the entity.
        """
        logger.debug(
            f'Saving `{self.entity_cls.__name__}` object')

        try:
            # If this is a new entity, generate ID
            if entity_obj.state_.is_new:
                if not getattr(entity_obj, entity_obj.meta_.id_field.field_name, None):
                    setattr(entity_obj, entity_obj.meta_.id_field.field_name, self.entity_cls._generate_identity())

            # Do unique checks, update the record and return the Entity
            self._validate_unique(entity_obj, create=False)

            # Build the model object and create it
            model_obj = self._create(self.model_cls.from_entity(entity_obj))

            # Update the auto fields of the entity
            for field_name, field_obj in entity_obj.meta_.declared_fields.items():
                if isinstance(field_obj, Auto):
                    if isinstance(model_obj, dict):
                        field_val = model_obj[field_name]
                    else:
                        field_val = getattr(model_obj, field_name)
                    setattr(entity_obj, field_name, field_val)

            # Set Entity status to saved
            entity_obj.state_.mark_saved()

            return entity_obj
        except Exception:
            # FIXME Log Exception
            raise

    def update(self, entity_obj, *data, **kwargs) -> 'BaseEntity':
        """Update a Record in the repository.

        Also performs unique validations before creating the entity.

        Supports both dictionary and keyword argument updates to the entity::

            dog.update({'age': 10})

            dog.update(age=10)

        :param data: Dictionary of values to be updated for the entity
        :param kwargs: keyword arguments with key-value pairs to be updated
        """
        logger.debug(f'Updating existing `{self.entity_cls.__name__}` object with id {entity_obj.id}')

        try:
            # Update entity's data attributes
            entity_obj._update_data(*data, **kwargs)

            # Do unique checks, update the record and return the Entity
            self._validate_unique(entity_obj, create=False)

            self._update(self.model_cls.from_entity(entity_obj))

            # Set Entity status to saved
            entity_obj.state_.mark_saved()

            return entity_obj
        except Exception:
            # FIXME Log Exception
            raise

    def _validate_unique(self, entity_obj, create=True):
        """ Validate the unique constraints for the entity """
        # Build the filters from the unique constraints
        filters, excludes = {}, {}

        for field_name, field_obj in self.entity_cls.meta_.unique_fields:
            lookup_value = getattr(entity_obj, field_name, None)
            # Ignore empty lookup values
            if lookup_value in Field.empty_values:
                continue
            # Ignore identifiers on updates
            if not create and field_obj.identifier:
                excludes[field_name] = lookup_value
                continue
            filters[field_name] = lookup_value

        # Lookup the objects by the filters and raise error on results
        for filter_key, lookup_value in filters.items():
            if self.exists(excludes, **{filter_key: lookup_value}):
                field_obj = self.entity_cls.meta_.declared_fields[filter_key]
                field_obj.fail('unique',
                               entity_name=self.entity_cls.__name__,
                               field_name=filter_key)

    def delete(self, entity_obj):
        """Delete a Record from the Repository

        will perform callbacks and run validations before deletion.

        Throws ObjectNotFoundError if the object was not found in the repository.
        """
        try:
            if not entity_obj.state_.is_destroyed:
                # Update entity's data attributes
                self._delete(self.model_cls.from_entity(entity_obj))

                # Set Entity status to saved
                entity_obj.state_.mark_destroyed()

            return entity_obj
        except Exception:
            # FIXME Log Exception
            raise

    def delete_all(self):
        """Delete all Records in a Repository

        Will skip callbacks and validations.
        """
        try:
            self._delete_all()
        except Exception:
            # FIXME Log Exception
            raise
