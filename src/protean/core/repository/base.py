# Standard Library Imports
import logging

# Protean
from protean.core.exceptions import IncorrectUsageError, ValidationError
from protean.core.field.association import HasMany, HasOne
from protean.domain import DomainObjects
from protean.globals import current_domain

logger = logging.getLogger("protean.repository")


class _RepositoryMetaclass(type):
    """
    This base metaclass processes the class declaration and constructs a meta object that can
    be used to introspect the Repository class later. Specifically, it sets up a `meta_` attribute on
    the Repository to an instance of Meta, either the default of one that is defined in the
    Repository class.

    `meta_` is setup with these attributes:
        * `aggregate`: The aggregate associated with the repository
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize Repository MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of Repository
        # (excluding Repository class itself).
        parents = [b for b in bases if isinstance(b, _RepositoryMetaclass)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Remove `abstract` in base classes if defined
        for base in bases:
            if hasattr(base, "Meta") and hasattr(base.Meta, "abstract"):
                delattr(base.Meta, "abstract")

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop("Meta", None)
        meta = attr_meta or getattr(new_class, "Meta", None)
        setattr(new_class, "meta_", RepositoryMeta(meta))

        return new_class


class RepositoryMeta:
    """ Metadata info for the Repository.

    An object of this class is either constructed automatically upon Repository class initialization, or
    a meta class can be explicitly passed along with the repository definition, as in inner `Meta` class.

    Options supported by Meta class:
    - ``aggregate_cls``: The aggregate associated with the repository
    """

    def __init__(self, meta):
        # The aggregate class with which the repository is associated
        #   Repository will be fetched via its associated aggregate.
        #
        # FIXME Validate that `aggregate_cls` is a Aggregate domain element
        self.aggregate_cls = getattr(meta, "aggregate_cls", None)


class BaseRepository(metaclass=_RepositoryMetaclass):
    """This is the baseclass for concrete Repository implementations.

    The three methods in this baseclass to `add`, `get` or `remove` entities are sufficient in most cases
    to handle application requirements. They have built-in support for handling child relationships and
    honor Unit of Work constructs. While they can be overriddent, it is generally suggested to call the
    parent method first before writing custom code.

    Repositories are strictly meant to be used in conjunction with Aggregate elements. While it is possible
    to link and use :ref:`entity`, it is always better to deal with persistence at the level of the transaction
    boundary, which is at the aggregate's level.
    """

    element_type = DomainObjects.REPOSITORY

    def __new__(cls, *args, **kwargs):
        # Prevent instantiation of `BaseRepository itself`
        if cls is BaseRepository:
            raise TypeError("BaseRepository cannot be instantiated")
        return super().__new__(cls)

    def add(self, aggregate):  # noqa: C901
        """This method helps persist or update aggregates into the persistence store.

        Returns the persisted aggregate.

        Protean adopts a collection-oriented design pattern to handle persistence. What this means is that
        the Repository interface does not hint in any way that there is an underlying persistence mechanism,
        avoiding any notion of saving or persisting data in the design layer. The task of syncing the data
        back into the persistence store is handled automatically.

        To be specific, a Repository mimics a `set` collection. Whatever the implementation, the repository
        will not allow instances of the same object to be added twice. Also, when retrieving objects from
        a Repository and modifying them, you don’t need to “re-save” them to the Repository.

        If there is a :ref:`Unit of Work <unit-of-work>` in progress, then the changes are performed on the
        UoW's active session. They are committed whenever the entire UoW is committed. If there is no
        transaction in progress, changes are committed immediately to the persistence store. This mechanism
        is part of the DAO's design, and is automatically used wherever one tries to persist data.
        """

        # Ensure that aggregate is clean and good to save
        # FIXME Let `clean()` raise validation errors
        errors = aggregate.clean() or {}
        # Raise any errors found during load
        if errors:
            logger.error(errors)
            raise ValidationError(errors)

        # If there are HasMany fields in the aggregate, sync child objects added/removed,
        #   but not yet persisted to the database.
        #
        # The details of in-transit child objects are maintained as part of the `has_many_field` itself
        #   in a variable called `_temp_cache`
        for field_name, field in aggregate.meta_.declared_fields.items():
            if isinstance(field, HasMany):
                has_many_field = getattr(aggregate, field_name)

                for item in has_many_field._temp_cache["removed"]:
                    dao = current_domain.get_dao(field.to_cls)
                    dao.delete(item)
                has_many_field._temp_cache[
                    "removed"
                ] = list()  # Empty contents of `removed` cache

                for item in has_many_field._temp_cache["added"]:
                    dao = current_domain.get_dao(field.to_cls)
                    item.state_.mark_new()
                    dao.save(item)
                has_many_field._temp_cache[
                    "added"
                ] = list()  # Empty contents of `added` cache

            if isinstance(field, HasOne):
                if field.has_changed:
                    dao = current_domain.get_dao(field.to_cls)
                    if field.change == "ADDED":
                        dao.save(field.value)
                    elif field.change == "UPDATED":
                        if field.change_old_value is not None:
                            # The object was replaced, so delete the old record
                            dao.delete(field.change_old_value)
                        else:
                            # The same object was updated, so mark it as new to be able to save
                            # FIXME This should have been automatic with `is_changed` flag in `state_`
                            field.value.state_.mark_new()

                        dao.save(field.value)
                    else:
                        dao.delete(field.change_old_value)

                    # Reset temporary fields after processing
                    field.change = None
                    field.change_old_value = None

        # Persist only if the aggregate object is new, or it has changed since last persistence
        if (not aggregate.state_.is_persisted) or (
            aggregate.state_.is_persisted and aggregate.state_.is_changed
        ):
            dao = current_domain.get_dao(self.meta_.aggregate_cls)
            dao.save(aggregate)

        return aggregate

    def remove(self, aggregate):
        """This method helps remove aggregates from the persistence store.

        Returns the removed aggregate.

        Protean mimics the behavior of a `set` collection in such methods. The repository promotes the
        illusion that we are dealing with collection like objects, so that the domain layer remains clean
        and oblivious to underlying persistence mechanisms. All changes are synced to the persistence store
        automatically by the Repository as and when appropriate.

        If there is a :ref:`Unit of Work <unit-of-work>` in progress, then the changes are performed on the
        UoW's active session. They are committed whenever the entire UoW is committed. If there is no
        transaction in progress, changes are committed immediately to the persistence store. This mechanism
        is part of the DAO's design, and is automatically used wherever one tries to persist data.
        """
        dao = current_domain.get_dao(self.meta_.aggregate_cls)
        dao.delete(aggregate)

        return aggregate

    def get(self, identifier):
        """This is a utility method to fetch data from the persistence store by its key identifier. All child objects,
        including enclosed entities, are returned as part of this call.

        Returns the fetched aggregate.

        All other data filtering capabilities can be implemented by using the underlying DAO's
        :meth:`BaseDAO.filter` method.

        Filter methods are typically implemented as domain-contextual queries, like `find_adults()`,
        `find_residents_of_area(zipcode)`, etc. It is also possible to make use of more complicated,
        domain-friendly design patterns like the `Specification` pattern.
        """
        dao = current_domain.get_dao(self.meta_.aggregate_cls)
        return dao.get(identifier)


class RepositoryFactory:
    @classmethod
    def prep_class(cls, element_cls, **kwargs):
        if issubclass(element_cls, BaseRepository):
            new_element_cls = element_cls
        else:
            try:
                new_dict = element_cls.__dict__.copy()
                new_dict.pop("__dict__", None)  # Remove __dict__ to prevent recursion

                new_element_cls = type(
                    element_cls.__name__, (BaseRepository,), new_dict
                )
            except BaseException as exc:
                logger.debug("Error during Element registration:", repr(exc))
                raise IncorrectUsageError(
                    "Invalid class {element_cls.__name__} for type {element_type.value}"
                    " (Error: {exc})",
                )

        cls._validate_repository_class(new_element_cls)

        if hasattr(new_element_cls, "meta_"):
            if not (
                hasattr(new_element_cls.meta_, "aggregate_cls")
                and new_element_cls.meta_.aggregate_cls
            ):
                new_element_cls.meta_.aggregate_cls = kwargs.pop("aggregate_cls", None)

            new_element_cls.meta_.bounded_context = kwargs.pop("bounded_context", None)

        if not new_element_cls.meta_.aggregate_cls:
            raise IncorrectUsageError(
                "Repositories need to be associated with an Aggregate"
            )

        return new_element_cls

    @classmethod
    def _validate_repository_class(cls, new_cls):
        if not issubclass(new_cls, BaseRepository):
            raise AssertionError(
                f"Element {new_cls.__name__} must be subclass of `BaseRepository`"
            )

        return True
