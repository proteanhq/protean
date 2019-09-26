# -*- coding: utf-8 -*-
"""
    protean.core.repository.dao
    ~~~~~~~~~
    This module contains the interface definition to be satisfed by concrete DAO implementations.
    :copyright: 2019 Protean
    :license: BSD-3-Clause
"""
# Standard Library Imports
import logging

from abc import ABCMeta, abstractmethod
from typing import Any

# Protean
from protean.core.entity import BaseEntity
from protean.core.exceptions import ObjectNotFoundError, TooManyObjectsError, ValidationError
from protean.core.field.basic import Auto, Field
from protean.core.queryset import QuerySet
from protean.globals import current_uow
from protean.utils.query import Q

# Local/Relative Imports
from .resultset import ResultSet

logger = logging.getLogger('protean.repository')


class BaseDAO(metaclass=ABCMeta):
    """This is the baseclass for concrete DAO implementations.

    One part of this base class contains abstract methods to be overridden and implemented in each
    concrete database implementation. These methods are where the actual interaction with the database
    takes place. The other part contains fully-implemented object lifecycle methods to help in persistence
    and data fetch. These methods invoke the concrete methods of each database implementation to
    complete their function.

    The lifecycle methods of DAO handle the casting of a model object to a domain entity object, and vice versa.

    :param domain: the domain of the application this DAO is associated with.
    :param provider: the corresponding provider object of the database implementation, from whom the DAO can
                     request and fetch sessions and connections.
    :param model_cls: the concrete model class associated with the DAO. The model class is a direct representation
                      of an object in ORM/ODM terms or as represented by a python driver.
    :param entity_cls: the domain entity class associated with the DAO.
    """

    def __init__(self, domain, provider, entity_cls, model_cls):
        #: Holds a reference to the domain to which the DAO belongs to.
        self.domain = domain

        #: Holds a reference to the provider which supplies the DAO with live connections.
        self.provider = provider

        #: Holds a reference to the model class representation required by the ORM/ODM or the python database driver.
        self.model_cls = model_cls

        #: Holds a reference to the entity class associated with this DAO.
        self.entity_cls = entity_cls

        #: An empty query object that can be used to begin filtering/querying operations
        #: on the underlying data store.
        self.query = QuerySet(self, domain, self.entity_cls)

        #: The actual database document or table name associated with the DAO.
        #: This is used for deriving namespaces for storage containers, especially the default dict provider.
        self.schema_name = entity_cls.meta_.schema_name

        #: Tracks whether the DAO needs to operate outside any active Unit of Work transactions.
        self._outside_uow = False

    def _get_session(self):
        """Returns an active connection to the persistence store.

        - If there is an active transaction, the connection associated with the transaction (in the UoW) is returned
        - If the DAO has been explicitly instructed to work outside a UoW (with the help of `_outside_uow`), or if
          there are no active transactions, a new connection is retrieved from the provider and returned.
        """
        if current_uow and not self._outside_uow:
            return current_uow.get_session(self.provider.name)
        else:
            return self.provider.get_connection()

    def outside_uow(self):
        """When called, the DAO is instructed to work outside active transactions."""
        self._outside_uow = True

        # Return the DAO object to support method chaining
        return self

    ###############################
    # Repository-specific methods #
    ###############################

    @abstractmethod
    def _filter(self, criteria: Q, offset: int = 0, limit: int = 10,
                order_by: list = ()) -> ResultSet:
        """
        Filter objects from the data store. Method must return a `ResultSet`
        object
        """

    @abstractmethod
    def _create(self, model_obj: Any):
        """Persist a new entity into the persistent store. Concrete implementation will be provided by
        the database DAO class.

        Method invocation should persist a new record in the data store.

        This method is invoked by the `create` wrapper and should not be called directly.

        Returns the persisted model object.

        :param model_obj: The model object supplied in an ORM/ODM/Python driver friendly/format
        """

    @abstractmethod
    def _update(self, model_obj: Any):
        """Update entity data in the persistence store. Concrete implementation will be provided by
        the database DAO class.

        Method invocation should update the existing data in the persistent store, by its unique identifier.

        This method is invoked by DAO's `update` wrapper method and should not be called directly.

        Returns the updated model object.

        :param model_obj: The model object supplied in an ORM/ODM/Python driver friendly/format
        """

    @abstractmethod
    def _update_all(self, criteria: Q, *args, **kwargs):
        """Perform a bulk update on the persistent store. Concrete implementation will be provided by
        the database DAO class.

        Method invocation should update all objects satisfying `criteria` with attributes specified in
        `args` and `kwargs`.

        This method is invoked by Queryset's `update_all()` method and should not be called directly.

        .. warning:: The `update_all()` method is a “bulk” operation, which bypasses ORM/ODM unit-of-work automation
            in favor of greater performance.

        Returns the count of rows matched for the provided criteria.

        :param criteria: A Q object wrapping one or more levels of criteria/filters
        :param args: A dictionary object containing attribute data to be updated
        :param kwargs: Keyword args specifying attribute data to be updated
        """

    @abstractmethod
    def _delete(self):
        """Delete this entity from the persistence store. Concrete implementation will be provided by
        the database DAO class.

        Method invocation should delete existing record in the persistent store, by its unique identifier.

        This method is invoked by DAO's `delete` wrapper method and should not be called directly.

        Returns the deleted model object.
        """

    @abstractmethod
    def _delete_all(self, criteria: Q = None):
        """Perform a bulk delete on the persistent store. Concrete implementation will be provided by
        the database DAO class.

        Method invocation should update all objects satisfying `criteria`.

        This method is invoked by Queryset's `delete_all()` method and should not be called directly.

        .. warning:: The `delete_all()` method is a “bulk” operation, which bypasses ORM/ODM unit-of-work automation
            in favor of greater performance.

        Returns the count of rows matched for the provided criteria.

        :param criteria: A Q object wrapping one or more levels of criteria/filters. If no criteria is provided,
                         then all records of the table/document are removed.
        """

    @abstractmethod
    def _raw(self, query: Any, data: Any = None):
        """Run raw query on Data source. Concrete implementation will be provided by
        the database DAO class.

        Method invocation should fetch all objects satisfying the raw query. Running a raw query on the data store
        should always returns entity instance objects. If the results were not synthesizable back into
        entity objects, an exception should be thrown.

        This method is invoked by Queryset's `raw()` method and should not be called directly.

        .. warning:: The `raw()` method bypasses ORM/ODM unit-of-work automation.

        Returns the result specified by the raw query.

        :param query: Raw query to be passed to the data store.
        :param data: Data to be passed to the data store as-is, along with the query
                     (in case of update statements, for example).
        """

    ######################
    # Life-cycle methods #
    ######################

    def get(self, identifier: Any) -> BaseEntity:
        """Retrieve a specific Record from the Repository by its `identifier`.

        This method internally uses the `filter` method to fetch records.

        Returns exactly one record that matches the identifier.

        Throws `ObjectNotFoundError` if no record was found for the identifier.

        Throws `TooManyObjectsError` if multiple records were found for the identifier.

        :param identifier: id of the record to be fetched from the data store.
        """
        logger.debug(f'Lookup `{self.entity_cls.__name__}` object with identifier {identifier}')

        # Filter on the ID field of the entity
        filters = {
            self.entity_cls.meta_.id_field.field_name: identifier
        }

        results = self.query.filter(**filters).all()
        if not results:
            raise ObjectNotFoundError(
                f'`{self.entity_cls.__name__}` object with identifier {identifier} '
                f'does not exist.')

        if len(results) > 1:
            raise TooManyObjectsError(
                f'More than one object of `{self.entity_cls.__name__}` exist with identifier {identifier}'
            )

        # Return the first result, because `filter` would have returned an array
        return results.first

    def find_by(self, **kwargs) -> 'BaseEntity':
        """Find a specific entity record that matches one or more criteria.

        This method internally uses the `filter` method to fetch records.

        Returns exactly one record that matches the identifier.

        Throws `ObjectNotFoundError` if no record was found for the identifier.
        Throws `TooManyObjectsError` if multiple records were found for the identifier.

        :param kwargs: named arguments of attribute names and values to filter on.
        """
        logger.debug(f'Lookup `{self.entity_cls.__name__}` object with values '
                     f'{kwargs}')

        # Filter for item in the data store
        results = self.query.filter(**kwargs).all()

        if not results:
            raise ObjectNotFoundError(
                f'`{self.entity_cls.__name__}` object with values {[item for item in kwargs.items()]} '
                f'does not exist.')

        if len(results) > 1:
            raise TooManyObjectsError(
                f'More than one object of `{self.entity_cls.__name__}` exist '
                f'with values {[item for item in kwargs.items()]}'
            )

        # Return the first result, because `filter` would have returned an array
        return results.first

    def exists(self, excludes_, **filters):
        """Returns `True` if objects matching the provided filters were found. Else, returns False.

        This method internally uses the `filter` method to fetch records. But it can be overridden for better and
        quicker implementations supported by databases.

        :param filters: criteria to match records against
        :param excludes_: criteria that records should not satisfy
        """
        results = self.query.filter(**filters).exclude(**excludes_)

        # Invokes the __bool__ method on `ResultSet`.
        return bool(results)

    def create(self, *args, **kwargs) -> 'BaseEntity':
        """Create a new record in the data store.

        Performs validations for unique attributes before creating the entity

        Returns the created entity object.

        Throws `ValidationError` for validation failures on attribute values or uniqueness constraints.

        :param args: Dictionary object containing the object's data.
        :param kwargs: named attribute names and values
        """
        logger.debug(
            f'Creating new `{self.entity_cls.__name__}` object using data {kwargs}')

        try:
            # Build the entity from input arguments
            # Raises validation errors, if any, at this point
            entity_obj = self.entity_cls(*args, **kwargs)

            # Perform unique checks. Raises validation errors if unique constraints are violated.
            self._validate_unique(entity_obj)

            # Build the model object and persist into data store
            model_obj = self._create(self.model_cls.from_entity(entity_obj))

            # Reverse update auto fields into entity
            for field_name, field_obj in entity_obj.meta_.declared_fields.items():
                if isinstance(field_obj, Auto) and not getattr(entity_obj, field_name):
                    if isinstance(model_obj, dict):
                        field_val = model_obj[field_name]
                    else:
                        field_val = getattr(model_obj, field_name)

                    setattr(entity_obj, field_name, field_val)

            # Set Entity status to saved to let everybody know it has been persisted
            entity_obj.state_.mark_saved()

            return entity_obj
        except ValidationError as exc:
            logger.error(f'Failed creating entity because of {exc}')
            raise

    def save(self, entity_obj):
        """Create or update an entity in the data store, depending on its state. An identity for entity record is
        generated, if not already present.

        The primary difference between `save` and other lifecycle methods like `create` and `update` is that `save`
        accepts a fully formed entity object to persist, while the others accept attribute params to build the
        entity model from.

        Returns the created/updated entity object.

        Throws `ValidationError` for validation failures on attribute values or uniqueness constraints.

        :param entity_obj: Entity object to be persisted
        """
        logger.debug(
            f'Saving `{self.entity_cls.__name__}` object')

        try:
            # Build the model object and create it
            if entity_obj.state_.is_persisted:
                model_obj = self._update(self.model_cls.from_entity(entity_obj))
            else:
                # If this is a new entity, generate ID
                if entity_obj.state_.is_new:
                    if not getattr(entity_obj, entity_obj.meta_.id_field.field_name, None):
                        setattr(entity_obj, entity_obj.meta_.id_field.field_name,
                                self.entity_cls._generate_identity())

                model_obj = self._create(self.model_cls.from_entity(entity_obj))

            updated_entity_obj = self.model_cls.to_entity(model_obj)

            # Update the auto fields of the entity
            for field_name, field_obj in entity_obj.meta_.declared_fields.items():
                if isinstance(field_obj, Auto):
                    field_val = getattr(updated_entity_obj, field_name)
                    setattr(entity_obj, field_name, field_val)

            # Set Entity status to saved to let everybody know it has been persisted
            entity_obj.state_.mark_saved()

            return entity_obj
        except Exception as exc:
            logger.error(f'Failed saving entity because of {exc}')
            raise

    def update(self, entity_obj, *data, **kwargs) -> 'BaseEntity':
        """Update a record in the data store.

        Performs validations for unique attributes before creating the entity.

        Supports both dictionary and keyword argument updates to the entity::

            >>> user.update({'age': 10})
            >>> user.update(age=10)

        Returns the updated entity object.

        Throws `ValidationError` for validation failures on attribute values or uniqueness constraints.

        :param entity_obj: The entity object to be updated
        :param data: Dictionary of values to be updated for the entity
        :param kwargs: keyword arguments of attribute pairs to be updated
        """
        logger.debug(f'Updating existing `{self.entity_cls.__name__}` object with id {entity_obj.id}')

        try:
            # Update entity's data attributes
            entity_obj._update_data(*data, **kwargs)

            # Do unique checks
            self._validate_unique(entity_obj, create=False)

            self._update(self.model_cls.from_entity(entity_obj))

            # Set Entity status to saved to let everybody know it has been persisted
            entity_obj.state_.mark_saved()

            return entity_obj
        except Exception as exc:
            logger.error(f'Failed updating entity because of {exc}')
            raise

    def _validate_unique(self, entity_obj, create=True):
        """Validate the unique constraints for the entity. Raise ValidationError, if constraints were violated.

        This method internally uses each field object's fail method to construct a valid error message.

        :param entity_obj: Entity object to be validated
        :param create: boolean value to indicate that the validation is part of a create operation
        """
        # Build the filters from the unique constraints
        filters, excludes = {}, {}

        # Construct filter criteria based on unique fields defined in Entity class
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

        # Lookup the objects by filters and raise error if objects exist
        for filter_key, lookup_value in filters.items():
            if self.exists(excludes, **{filter_key: lookup_value}):
                field_obj = self.entity_cls.meta_.declared_fields[filter_key]
                field_obj.fail('unique',
                               entity_name=self.entity_cls.__name__,
                               field_name=filter_key)

    def delete(self, entity_obj):
        """Delete a record in the data store.

        Performs validations before data deletion.

        Returns the deleted entity object.

        Throws ObjectNotFoundError if the object was not found in the data store.

        :param entity_obj: Entity object to be deleted from data store
        """
        try:
            if not entity_obj.state_.is_destroyed:
                self._delete(self.model_cls.from_entity(entity_obj))

                # Set Entity status to destroyed to let everybody know the object is no longer referable
                entity_obj.state_.mark_destroyed()

            return entity_obj
        except Exception as exc:
            logger.error(f'Failed entity deletion because of {exc}')
            raise

    def delete_all(self):
        """Delete all records in this table/document in the persistent store.

        Does not perform validations before data deletion.
        Does not return confirmation of data deletion.
        """
        try:
            self._delete_all()
        except Exception as exc:
            logger.error(f'Failed deletion of all records because of {exc}')
            raise
