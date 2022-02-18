import logging

from functools import lru_cache

from protean.container import Element, OptionsMixin
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import HasMany, HasOne
from protean.globals import current_domain
from protean.reflection import declared_fields
from protean.utils import (
    Database,
    DomainObjects,
    derive_element_class,
    fully_qualified_name,
)

logger = logging.getLogger(__name__)


class BaseRepository(Element, OptionsMixin):
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

    @classmethod
    def _default_options(cls):
        return [("aggregate_cls", None), ("database", "ALL")]

    def __new__(cls, *args, **kwargs):
        # Prevent instantiation of `BaseRepository itself`
        if cls is BaseRepository:
            raise TypeError("BaseRepository cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, domain, provider) -> None:
        self._domain = domain
        self._provider = provider

    @property
    @lru_cache()
    def _model(self):
        """Retrieve Model class connected to Entity"""
        # If a model was associated with the aggregate record, give it a higher priority
        #   and do not bake a new model class from aggregate/entity attributes
        custom_model_cls = None
        if fully_qualified_name(self.meta_.aggregate_cls) in self._domain._models:
            custom_model_cls = self._domain._models[
                fully_qualified_name(self.meta_.aggregate_cls)
            ]

        # FIXME This is the provide support for activating database specific models
        #   This needs to be enhanced to allow Protean to hold multiple models per Aggregate/Entity
        #   per database.
        #
        #   If no database is specified, model can be used for all databases
        if custom_model_cls and (
            custom_model_cls.meta_.database is None
            or custom_model_cls.meta_.database == self._provider.conn_info["DATABASE"]
        ):
            # Get the decorated model class.
            #   This is a no-op if the provider decides that the model is fully-baked
            model_cls = self._provider.decorate_model_class(
                self.meta_.aggregate_cls, custom_model_cls
            )
        else:
            # No model was associated with the aggregate/entity explicitly.
            #   So ask the Provider to bake a new model, initialized properly for this aggregate
            #   and return it
            model_cls = self._provider.construct_model_class(self.meta_.aggregate_cls)

        return model_cls

    @property
    @lru_cache()
    def _dao(self):
        """Retrieve a DAO registered for the Aggregate with a live connection"""
        # Fixate on Model class at the domain level because an explicit model may have been registered
        return self._provider.get_dao(self.meta_.aggregate_cls, self._model)

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
        for field_name, field in declared_fields(aggregate).items():
            if isinstance(field, HasMany):
                for _, item in aggregate._temp_cache[field_name]["removed"].items():
                    current_domain.repository_for(field.to_cls)._dao.delete(item)
                aggregate._temp_cache[field_name][
                    "removed"
                ] = {}  # Empty contents of `removed` cache

                for _, item in aggregate._temp_cache[field_name]["updated"].items():
                    current_domain.repository_for(field.to_cls)._dao.save(item)
                aggregate._temp_cache[field_name][
                    "updated"
                ] = {}  # Empty contents of `added` cache

                for _, item in aggregate._temp_cache[field_name]["added"].items():
                    item.state_.mark_new()
                    current_domain.repository_for(field.to_cls)._dao.save(item)
                aggregate._temp_cache[field_name][
                    "added"
                ] = {}  # Empty contents of `added` cache

            if isinstance(field, HasOne):
                if field.has_changed:
                    to_cls_repo = current_domain.repository_for(field.to_cls)
                    if field.change == "ADDED":
                        to_cls_repo._dao.save(field.value)
                    elif field.change == "UPDATED":
                        if field.change_old_value is not None:
                            # The object was replaced, so delete the old record
                            to_cls_repo._dao.delete(field.change_old_value)
                        else:
                            # The same object was updated
                            # FIXME This should have been automatic with `is_changed` flag in `state_`
                            field.value.state_.mark_changed()

                        to_cls_repo._dao.save(field.value)
                    else:
                        to_cls_repo._dao.delete(field.change_old_value)

                    # Reset temporary fields after processing
                    field.change = None
                    field.change_old_value = None

        # Persist only if the aggregate object is new, or it has changed since last persistence
        if (not aggregate.state_.is_persisted) or (
            aggregate.state_.is_persisted and aggregate.state_.is_changed
        ):
            self._dao.save(aggregate)

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
        return self._dao.get(identifier)

    def all(self):
        """This is a utility method to fetch all records of own type from persistence store.

        Returns a list of all records."""
        return self._dao.query.all().items


def repository_factory(element_cls, **opts):
    element_cls = derive_element_class(element_cls, BaseRepository, **opts)

    if not element_cls.meta_.aggregate_cls:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Repository `{element_cls.__name__}` should be associated with an Aggregate"
                ]
            }
        )

    # FIXME Uncomment
    # if not issubclass(element_cls.meta_.aggregate_cls, BaseAggregate):
    #     raise IncorrectUsageError(
    #         {"_entity": [f"Repository `{element_cls.__name__}` can only be associated with an Aggregate"]}
    #     )

    # Ensure the value of `database` is among known databases
    if element_cls.meta_.database != "ALL" and element_cls.meta_.database not in [
        database.value for database in Database
    ]:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Repository `{element_cls.__name__}` should be associated with a valid Database"
                ]
            }
        )

    return element_cls
