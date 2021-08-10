import logging

from protean.core.field.association import HasMany, HasOne
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.globals import current_domain
from protean.utils import Database, DomainObjects, derive_element_class
from protean.utils.container import BaseContainer

logger = logging.getLogger("protean.repository")


class BaseRepository(BaseContainer):
    """This is the baseclass for concrete Repository implementations.

    The three methods in this baseclass to `add`, `get` or `remove` entities are sufficient in most cases
    to handle application requirements. They have built-in support for handling child relationships and
    honor Unit of Work constructs. While they can be overriddent, it is generally suggested to call the
    parent method first before writing custom code.

    Repositories are strictly meant to be used in conjunction with Aggregate elements. While it is possible
    to link and use :ref:`user-entity`, it is always better to deal with persistence at the level of the transaction
    boundary, which is at the aggregate's level.
    """

    element_type = DomainObjects.REPOSITORY

    META_OPTIONS = [("aggregate_cls", None), ("database", "ALL")]

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
                for _, item in aggregate._temp_cache[field_name]["removed"].items():
                    dao = current_domain.get_dao(field.to_cls)
                    dao.delete(item)
                aggregate._temp_cache[field_name][
                    "removed"
                ] = {}  # Empty contents of `removed` cache

                for _, item in aggregate._temp_cache[field_name]["updated"].items():
                    dao = current_domain.get_dao(field.to_cls)
                    dao.save(item)
                aggregate._temp_cache[field_name][
                    "updated"
                ] = {}  # Empty contents of `added` cache

                for _, item in aggregate._temp_cache[field_name]["added"].items():
                    dao = current_domain.get_dao(field.to_cls)
                    item.state_.mark_new()
                    dao.save(item)
                aggregate._temp_cache[field_name][
                    "added"
                ] = {}  # Empty contents of `added` cache

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
                            # The same object was updated
                            # FIXME This should have been automatic with `is_changed` flag in `state_`
                            field.value.state_.mark_changed()

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

    def all(self):
        """This is a utility method to fetch all records of own type from persistence store.

        Returns a list of all records."""
        dao = current_domain.get_dao(self.meta_.aggregate_cls)
        return dao.query.all().items


def repository_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseRepository, **kwargs)

    if not element_cls.meta_.aggregate_cls:
        raise IncorrectUsageError(
            "Repositories need to be associated with an Aggregate"
        )

    # FIXME Uncomment
    # if not issubclass(element_cls.meta_.aggregate_cls, BaseAggregate):
    #     raise IncorrectUsageError(
    #         {"entity": ["Repositories can only be associated with an Aggregate"]}
    #     )

    # Ensure the value of `database` is among known databases
    if element_cls.meta_.database != "ALL" and element_cls.meta_.database not in [
        database.value for database in Database
    ]:
        raise IncorrectUsageError(
            {"entity": ["Repositories should be associated with a valid Database"]}
        )

    return element_cls
