import logging
from abc import ABCMeta, abstractmethod
from typing import TYPE_CHECKING, Any

from protean.core.database_model import BaseDatabaseModel
from protean.core.entity import BaseEntity
from protean.core.queryset import QuerySet, ResultSet
from protean.exceptions import (
    ExpectedVersionError,
    ObjectNotFoundError,
    TooManyObjectsError,
    ValidationError,
)
from protean.port.provider import BaseProvider
from protean.utils import DomainObjects
from protean.utils.globals import current_domain, current_uow
from protean.utils.query import Q
from protean.utils.reflection import declared_fields, id_field, unique_fields

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class BaseDAO(metaclass=ABCMeta):
    """Base class for concrete DAO (Data Access Object) implementations.

    A DAO bridges the domain entity layer and the database. It has two parts:

    1. **Abstract methods** (``_filter``, ``_create``, ``_update``,
       ``_update_all``, ``_delete``, ``_delete_all``, ``_raw``, ``has_table``)
       — override these in your adapter to interact with the database.

    2. **Lifecycle methods** (``get``, ``save``, ``create``, ``update``,
       ``delete``) — fully implemented wrappers that handle entity ↔ model
       conversion, version checking, UoW tracking, and then delegate to
       the abstract internals above.

    See ``BaseProvider`` in ``protean.port.provider`` for the full adapter
    development guide, including the call-flow diagram showing how the
    framework invokes DAO methods.

    :param domain: the domain of the application this DAO is associated with.
    :param provider: the corresponding provider object of the database
        implementation, from whom the DAO can request sessions and connections.
    :param database_model_cls: the concrete model class associated with the
        DAO. The model class is a direct representation of an object in
        ORM/ODM terms or as represented by a python driver.
    :param entity_cls: the domain entity class associated with the DAO.
    """

    def __init__(
        self,
        domain: "Domain",
        provider: BaseProvider,
        entity_cls: BaseEntity,
        database_model_cls: BaseDatabaseModel,
    ):
        #: Holds a reference to the domain to which the DAO belongs to.
        self.domain = domain

        #: Holds a reference to the provider which supplies the DAO with live connections.
        self.provider = provider

        #: Holds a reference to the model class representation required by the ORM/ODM or the python database driver.
        self.database_model_cls = database_model_cls

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

    def _get_session(self) -> Any:
        """Returns an active connection to the persistence store.

        - If there is an active transaction, the connection associated with the transaction (in the UoW) is returned
        - If the DAO has been explicitly instructed to work outside a UoW (with the help of `_outside_uow`), or if
          there are no active transactions, a new connection is retrieved from the provider and returned.
        """
        if current_uow and not self._outside_uow:
            return current_uow.get_session(self.provider.name)
        else:
            return self.provider.get_connection()

    @property
    def _is_standalone(self) -> bool:
        """Check if this DAO is operating outside a Unit of Work.

        Returns True when the DAO must manage its own commit/rollback/close
        lifecycle — either because there is no active UoW, or because the DAO
        has been explicitly instructed to work outside it.
        """
        return not current_uow or self._outside_uow

    def _commit_if_standalone(self, conn) -> None:
        """Commit the connection if we're not inside a Unit of Work.

        When operating within a UoW, the UoW handles commit/rollback/close.
        When standalone, we commit immediately and handle errors.
        """
        if self._is_standalone:
            try:
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _sync_event_position(self, entity: BaseEntity) -> None:
        """Sync the aggregate's event position from the event store.

        When an aggregate is loaded from the persistence store, its
        ``_event_position`` must reflect the last written event so that
        optimistic concurrency control (expected-version checks) works
        correctly on subsequent ``raise_()`` calls.

        This is a no-op for non-aggregate entities.
        """
        if entity.element_type != DomainObjects.AGGREGATE:
            return

        id_f = id_field(entity)
        assert id_f is not None
        identifier = getattr(entity, id_f.field_name)
        last_message = current_domain.event_store.store.read_last_message(
            f"{entity.meta_.stream_category}-{identifier}"
        )
        if last_message:
            assert last_message.metadata is not None
            assert last_message.metadata.event_store is not None
            entity._event_position = last_message.metadata.event_store.position

    def _track_in_uow(self, entity: BaseEntity) -> None:
        """Register the aggregate in the active Unit of Work's identity map.

        Tracking loaded aggregates lets the UoW collect domain events
        raised during the transaction and persist them on commit.

        This is a no-op for non-aggregate entities or when there is no
        active UoW.
        """
        if current_uow and entity.element_type == DomainObjects.AGGREGATE:
            current_uow._add_to_identity_map(entity)

    def outside_uow(self):
        """When called, the DAO is instructed to work outside active transactions."""
        self._outside_uow = True

        # Return the DAO object to support method chaining
        return self

    ###############################
    # Repository-specific methods #
    ###############################

    @abstractmethod
    def _filter(
        self, criteria: Q, offset: int = 0, limit: int = 10, order_by: list = ()
    ) -> ResultSet:
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

        This method is invoked by the DAO's `update` wrapper method and should not be called directly.

        Returns the updated model object.

        :param model_obj: The model object supplied in an ORM/ODM/Python driver friendly/format
        """

    @abstractmethod
    def _update_all(self, criteria: Q, *args, **kwargs):
        """Perform a bulk update on the persistent store.

        Concrete implementation will be provided by the database DAO class.
        Updates all objects satisfying ``criteria`` with attributes specified
        in ``args`` (a dict) and/or ``kwargs``.

        .. warning::

            This is an **internal framework method** reserved for
            infrastructure needs (outbox, projection rebuilds).  It bypasses
            domain validation, invariants, and the Unit of Work.  Do not call
            it from domain-level code.

        Returns the count of rows matched for the provided criteria.

        :param criteria: A ``Q`` object wrapping one or more filter conditions.
        :param args: A dictionary of attribute data to be updated.
        :param kwargs: Keyword args specifying attribute data to be updated.
        """

    @abstractmethod
    def _delete(self, model_obj: Any):
        """Delete this entity from the persistence store. Concrete implementation will be provided by
        the database DAO class.

        Method invocation should delete existing record in the persistent store, by its unique identifier.

        This method is invoked by DAO's `delete` wrapper method and should not be called directly.

        Returns the deleted model object.

        :param model_obj: The model object supplied in an ORM/ODM/Python driver friendly/format
        """

    @abstractmethod
    def _delete_all(self, criteria: Q = None):
        """Perform a bulk delete on the persistent store.

        Concrete implementation will be provided by the database DAO class.
        Deletes all objects satisfying ``criteria``.

        .. warning::

            This is an **internal framework method** reserved for
            infrastructure needs (outbox, projection rebuilds, table cleanup).
            It bypasses domain validation, invariants, and the Unit of Work.
            Do not call it from domain-level code.

        Returns the count of rows matched for the provided criteria.

        :param criteria: A ``Q`` object wrapping one or more filter conditions.
            If ``None``, all records of the table/document are removed.
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

    @abstractmethod
    def has_table(self) -> bool:
        """Check if the table/collection exists in the data store.

        Returns True if the table/collection exists, False otherwise.

        :return: Boolean indicating if the table/collection exists
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
        logger.debug(
            f"Lookup `{self.entity_cls.__name__}` object with identifier {identifier}"
        )

        # Filter on the ID field of the entity
        entity_id_field = id_field(self.entity_cls)
        assert entity_id_field is not None, (
            f"`{self.entity_cls.__name__}` does not have an identity field"
        )
        filters = {
            entity_id_field.field_name: identifier,
        }

        results = self.query.filter(**filters).all()  # type: ignore[reportCallIssue]
        if not results:
            raise ObjectNotFoundError(
                f"`{self.entity_cls.__name__}` object with identifier {identifier} "
                f"does not exist."
            )

        if len(results) > 1:
            raise TooManyObjectsError(
                f"More than one object of `{self.entity_cls.__name__}` exist with identifier {identifier}",
            )

        # Return the first result, because `filter` would have returned an array
        return results.first

    def find_by(self, **kwargs: Any) -> "BaseEntity":
        """Find a specific entity record that matches one or more criteria.

        This method internally uses the `filter` method to fetch records.

        Returns exactly one record that matches the identifier.

        Throws `ObjectNotFoundError` if no record was found for the identifier.
        Throws `TooManyObjectsError` if multiple records were found for the identifier.

        :param kwargs: named arguments of attribute names and values to filter on.
        """
        logger.debug(f"Lookup `{self.entity_cls.__name__}` object with values {kwargs}")

        # Filter for item in the data store
        results = self.query.filter(**kwargs).all()

        if not results:
            raise ObjectNotFoundError(
                f"`{self.entity_cls.__name__}` object with values {[item for item in kwargs.items()]} "
                f"does not exist."
            )

        if len(results) > 1:
            raise TooManyObjectsError(
                f"More than one object of `{self.entity_cls.__name__}` exist "
                f"with values {[item for item in kwargs.items()]}",
            )

        # Return the first result, because `filter` would have returned an array
        result = results.first
        assert result is not None
        return result

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

    def create(self, *args, **kwargs) -> "BaseEntity":
        """Create a new record in the data store.

        Performs validations for unique attributes before creating the entity

        Returns the created entity object.

        Throws `ValidationError` for validation failures on attribute values or uniqueness constraints.

        :param args: Dictionary object containing the object's data.
        :param kwargs: named attribute names and values
        """
        logger.debug(
            f"Creating new `{self.entity_cls.__name__}` object using data {kwargs}"
        )

        try:
            # Build the entity from input arguments
            # Raises validation errors, if any, at this point
            entity_obj = self.entity_cls(*args, **kwargs)  # type: ignore[reportCallIssue]

            # Perform unique checks. Raises validation errors if unique constraints are violated.
            self._validate_unique(entity_obj)

            # Build the model object and persist into data store
            model_obj = self._create(self.database_model_cls.from_entity(entity_obj))

            # Reverse update auto fields into entity
            for field_name, field_obj in declared_fields(entity_obj).items():
                is_auto = getattr(field_obj, "increment", False)
                if is_auto and not getattr(entity_obj, field_name):
                    if isinstance(model_obj, dict):
                        field_val = model_obj[field_name]
                    else:
                        field_val = getattr(model_obj, field_name)

                    setattr(entity_obj, field_name, field_val)

            # Set Entity status to saved to let everybody know it has been persisted
            entity_obj.state_.mark_saved()

            # Track aggregate at the UoW level, to be able to perform actions on UoW commit,
            #   like persisting events raised by the aggregate.
            if current_uow and entity_obj.element_type == DomainObjects.AGGREGATE:
                current_uow._add_to_identity_map(entity_obj)

            return entity_obj
        except ValidationError as exc:
            logger.error(f"Failed creating entity because of {exc}")
            raise

    def _validate_and_update_version(self, entity_obj) -> None:
        if entity_obj.state_.is_persisted:
            entity_id_field = id_field(self.entity_cls)
            assert entity_id_field is not None, (
                f"`{self.entity_cls.__name__}` does not have an identity field"
            )
            identifier = getattr(entity_obj, entity_id_field.field_name)
            persisted_entity = self.get(identifier)

            # The version of aggregate in the persistence store should be the same as
            #   the version we are dealing with.
            if persisted_entity._version != entity_obj._version:
                raise ExpectedVersionError(
                    f"Wrong expected version: {entity_obj._version} "
                    f"(Aggregate: {self.entity_cls.__name__}({identifier}), Version: {persisted_entity._version})"
                )

        # Now that we are certain we are dealing with the correct version,
        #   we can safely update the version to the next version.
        entity_obj._version = entity_obj._next_version

    def save(self, entity_obj: Any) -> Any:
        """Create or update an entity in the data store, depending on its state. An identity for entity record is
        generated, if not already present.

        The primary difference between `save` and other lifecycle methods like `create` and `update` is that `save`
        accepts a fully formed entity object to persist, while the others accept attribute params to build the
        entity model from.

        Returns the created/updated entity object.

        Throws `ValidationError` for validation failures on attribute values or uniqueness constraints.

        :param entity_obj: Entity object to be persisted
        """
        logger.debug(f"Saving `{self.entity_cls.__name__}` object")

        if entity_obj.element_type == DomainObjects.AGGREGATE:
            self._validate_and_update_version(entity_obj)

        try:
            # Build the model object and create it
            if entity_obj.state_.is_persisted:
                self._update(self.database_model_cls.from_entity(entity_obj))
            else:
                # Perform unique checks. Raises validation errors if unique constraints are violated.
                self._validate_unique(entity_obj)

                self._create(self.database_model_cls.from_entity(entity_obj))

            # Set Entity status to saved to let everybody know it has been persisted
            entity_obj.state_.mark_saved()

            # Track aggregate at the UoW level, to be able to perform actions on UoW commit,
            #   like persisting events raised by the aggregate.
            if current_uow and entity_obj.element_type == DomainObjects.AGGREGATE:
                # The element may have changed from the time it was loaded or may have been
                #   updated multiple times. We retain the last copy in seen.
                current_uow._add_to_identity_map(entity_obj)

            return entity_obj
        except Exception as exc:
            logger.error(f"Failed saving entity because {exc}")
            raise

    def update(self, entity_obj, *data, **kwargs) -> "BaseEntity":
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
        logger.debug(
            f"Updating existing `{self.entity_cls.__name__}` object with id {entity_obj.id}"
        )

        try:
            # Update entity's data attributes
            entity_obj._update_data(*data, **kwargs)

            # Do unique checks
            self._validate_unique(entity_obj, create=False)

            self._update(self.database_model_cls.from_entity(entity_obj))

            # Set Entity status to saved to let everybody know it has been persisted
            entity_obj.state_.mark_saved()

            # Track aggregate at the UoW level, to be able to perform actions on UoW commit,
            #   like persisting events raised by the aggregate.
            if current_uow and entity_obj.element_type == DomainObjects.AGGREGATE:
                current_uow._add_to_identity_map(entity_obj)

            return entity_obj
        except Exception as exc:
            logger.error(f"Failed updating entity because of {exc}")
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
        for field_name, field_obj in unique_fields(self.entity_cls).items():
            lookup_value = getattr(entity_obj, field_name, None)

            # Ignore empty lookup values
            if lookup_value in (None, "", [], (), {}):
                continue

            # Ignore identifiers on updates
            if not create and field_obj.identifier:
                excludes[field_name] = lookup_value
                continue

            filters[field_name] = lookup_value

        # Lookup the objects by filters and raise error if objects exist
        for filter_key, lookup_value in filters.items():
            if self.exists(excludes, **{filter_key: lookup_value}):
                field_obj = declared_fields(self.entity_cls)[filter_key]
                field_obj.fail(
                    "unique",
                    entity_name=self.entity_cls.__name__,
                    field_name=filter_key,
                    value=lookup_value,
                )

    def delete(self, entity_obj: Any) -> None:
        """Delete a record in the data store.

        Performs validations before data deletion.

        Returns the deleted entity object.

        Throws ObjectNotFoundError if the object was not found in the data store.

        :param entity_obj: Entity object to be deleted from data store
        """
        try:
            if not entity_obj.state_.is_destroyed:
                self._delete(self.database_model_cls.from_entity(entity_obj))

                # Set Entity status to destroyed to let everybody know the object is no longer referable
                entity_obj.state_.mark_destroyed()

            return entity_obj
        except Exception as exc:
            logger.error(f"Failed entity deletion because of {exc}")
            raise

    def delete_all(self):
        """Delete all records in this table/document in the persistent store.

        Does not perform validations before data deletion.
        Does not return confirmation of data deletion.
        """
        try:
            self._delete_all()
        except Exception as exc:
            logger.error(f"Failed deletion of all records because of {exc}")
            raise


class BaseLookup(metaclass=ABCMeta):
    """Base Lookup class to implement for each lookup

    Inspired by the lookup mechanism implemented in Django.

    Each lookup, which is simply a data comparison (like `name == 'John'`), is implemented as a subclass of this
    class, and has to implement the `as_expression()` method to provide the representation that the persistence
    store needs.

    Lookups are identified by their names, and the names are stored in the `lookup_name` class variable.
    """

    lookup_name = None

    def __init__(self, source, target, *, database_model_cls=None):
        """Source is LHS and Target is RHS of a comparsion.

        For example, in the expression `name == 'John'`, `name` is source (LHS) and `'John'` is target (RHS).
        In other words, source is the key/column/attribute to be searched on, and target is the value present in the
        persistent store.

        :param source: The key/column/attribute (LHS of the comparison)
        :param target: The value to compare against (RHS of the comparison)
        :param database_model_cls: Optional database model class for adapter-specific lookups
        """
        self.source, self.target = source, target
        self.database_model_cls = database_model_cls

    def process_source(self):
        """This is a blank implementation that simply returns the source.

        Returns `source` (LHS of the expression).

        You can override this method to manipulate the source when necessary. For example, if you are using a
        data store that cannot perform case-insensitive queries, it may be useful to always compare in lowercase.
        """
        return self.source

    def process_target(self):
        """This is a blank implementation that simply returns the target.

        Returns `target` (RHS of the expression).

        You can override this method to manipulate the target when necessary. A good example of overriding this
        method is when you are using a data store that needs strings to be enclosed in single quotes.
        """
        return self.target

    @abstractmethod
    def as_expression(self):
        """This methods should return the source and the target in the format required by the persistence store.

        Concrete implementation for this method varies from database to database.
        """
