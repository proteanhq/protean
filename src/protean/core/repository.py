from __future__ import annotations

import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Union

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.unit_of_work import UnitOfWork
from protean.core.view import BaseView
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import HasMany, HasOne
from protean.port.dao import BaseDAO
from protean.port.provider import BaseProvider
from protean.utils import (
    Database,
    DomainObjects,
    derive_element_class,
    fully_qualified_name,
)
from protean.utils.container import Element, OptionsMixin
from protean.utils.globals import current_uow
from protean.utils.reflection import association_fields, has_association_fields

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class BaseRepository(Element, OptionsMixin):
    """This is the baseclass for concrete Repository implementations.

    The three methods in this baseclass to `add`, `get` or `all` entities are sufficient in most cases
    to handle application requirements. They have built-in support for handling child relationships and
    honor Unit of Work constructs. While they can be overridden, it is generally suggested to call the
    parent method first before writing custom code.

    Repositories are strictly meant to be used in conjunction with Aggregate elements. It is always prudent to deal
    with persistence at the transaction boundary, which is at an Aggregate's level.
    """

    element_type = DomainObjects.REPOSITORY

    @classmethod
    def _default_options(cls):
        return [("database", "ALL"), ("part_of", None)]

    def __new__(cls, *args, **kwargs):
        # Prevent instantiation of `BaseRepository itself`
        if cls is BaseRepository:
            raise NotSupportedError("BaseRepository cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, domain: Domain, provider: BaseProvider) -> None:
        self._domain = domain
        self._provider = provider

    @property
    @lru_cache()
    def _model(self):
        """Retrieve Model class connected to Entity"""
        # If a model was associated with the aggregate record, give it a higher priority
        #   and do not bake a new model class from aggregate/entity attributes
        custom_model_cls = None
        if fully_qualified_name(self.meta_.part_of) in self._domain._models:
            custom_model_cls = self._domain._models[
                fully_qualified_name(self.meta_.part_of)
            ]

        # FIXME This is the provide support for activating database specific models
        #   This needs to be enhanced to allow Protean to hold multiple models per Aggregate/Entity
        #   per database.
        #
        #   If no database is specified, model can be used for all databases
        if custom_model_cls and (
            custom_model_cls.meta_.database is None
            or custom_model_cls.meta_.database == self._provider.__class__.__database__
        ):
            # Get the decorated model class.
            #   This is a no-op if the provider decides that the model is fully-baked
            model_cls = self._provider.decorate_model_class(
                self.meta_.part_of, custom_model_cls
            )
        else:
            # No model was associated with the aggregate/entity explicitly.
            #   So ask the Provider to bake a new model, initialized properly for this aggregate
            #   and return it
            model_cls = self._provider.construct_model_class(self.meta_.part_of)

        return model_cls

    @property
    @lru_cache()
    def _dao(self) -> BaseDAO:
        """Retrieve a DAO registered for the Aggregate with a live connection"""
        # Fixate on Model class at the domain level because an explicit model may have been registered
        return self._provider.get_dao(self.meta_.part_of, self._model)

    def add(
        self, item: Union[BaseAggregate, BaseView]
    ) -> Union[BaseAggregate, BaseView]:  # noqa: C901
        """This method helps persist or update aggregates or views into the persistence store.

        Returns the persisted item.

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
        # `add` is typically invoked in handler methods in Command Handlers and Event Handlers, which are
        #   enclosed in a UoW automatically. Therefore, if there is a UoW in progress, we can assume
        #   that it is the active session. If not, we will start a new UoW and commit it after the operation
        #   is complete.
        own_current_uow = None
        if not (current_uow and current_uow.in_progress):
            own_current_uow = UnitOfWork()
            own_current_uow.start()

        # If there are HasMany/HasOne fields in the aggregate, sync child objects added/removed,
        if has_association_fields(item):
            self._sync_children(item)

        # Persist only if the item object is new, or it has changed since last persistence
        if (not item.state_.is_persisted) or (
            item.state_.is_persisted and item.state_.is_changed
        ):
            self._dao.save(item)

            # If Aggregate has signed up Fact Events, raise them now
            if item.element_type == DomainObjects.AGGREGATE and item.meta_.fact_events:
                payload = item.to_dict()

                # Remove state attribute from the payload, as it is not needed for the Fact Event
                payload.pop("state_", None)

                # Construct and raise the Fact Event
                fact_event = item._fact_event_cls(**payload)
                item.raise_(fact_event)

        # If we started a UnitOfWork, commit it now
        if own_current_uow:
            own_current_uow.commit()

        return item

    def _sync_children(self, entity):
        """Recursively sync child entities to the persistence store"""
        # If there are HasMany fields in the aggregate, sync child objects added/removed,
        #   but not yet persisted to the database.
        #
        # The details of in-transit child objects are maintained as part of the `has_many_field` itself
        #   in a variable called `_temp_cache`
        for field_name, field in association_fields(entity).items():
            ### RECURSIVE SYNC ###
            # Start at the innermost child and work our way up
            if has_association_fields(field.to_cls):
                if isinstance(field, HasMany):
                    for item in getattr(entity, field_name):
                        self._sync_children(item)
                elif isinstance(field, HasOne):
                    if getattr(entity, field_name):
                        self._sync_children(getattr(entity, field_name))
            ### RECURSIVE SYNC ###

            if isinstance(field, HasMany):
                # First, handle direct updates to underlying child objects
                #   These are ones whose attributes have been changed directly
                #   instead of being routed via `add`/`remove`
                for item in getattr(entity, field_name):
                    if item.state_.is_changed:
                        # If the item was changed directly AND added via `add`, then
                        #   we give preference to the object in the cache
                        if item not in entity._temp_cache[field_name]["updated"]:
                            self._domain.repository_for(field.to_cls)._dao.save(item)

                for _, item in entity._temp_cache[field_name]["removed"].items():
                    self._domain.repository_for(field.to_cls)._dao.delete(item)
                entity._temp_cache[field_name][
                    "removed"
                ] = {}  # Empty contents of `removed` cache

                for _, item in entity._temp_cache[field_name]["updated"].items():
                    self._domain.repository_for(field.to_cls)._dao.save(item)
                entity._temp_cache[field_name][
                    "updated"
                ] = {}  # Empty contents of `updated` cache

                for _, item in entity._temp_cache[field_name]["added"].items():
                    item.state_.mark_new()
                    self._domain.repository_for(field.to_cls)._dao.save(item)
                entity._temp_cache[field_name][
                    "added"
                ] = {}  # Empty contents of `added` cache

            if isinstance(field, HasOne):
                # First, handle direct updates to underlying child objects
                #   These are ones whose attributes have been changed directly
                #   instead of being routed via `add`/`remove`
                item = getattr(entity, field_name)
                to_cls_repo = self._domain.repository_for(field.to_cls)
                if item is not None and item.state_.is_changed:
                    to_cls_repo._dao.save(item)
                # Or a new instance has been assigned
                elif entity._temp_cache[field_name]["change"]:
                    if entity._temp_cache[field_name]["change"] == "ADDED":
                        to_cls_repo._dao.save(item)
                    elif entity._temp_cache[field_name]["change"] == "UPDATED":
                        if entity._temp_cache[field_name]["old_value"] is not None:
                            # The object was replaced, so delete the old record
                            to_cls_repo._dao.delete(
                                entity._temp_cache[field_name]["old_value"]
                            )
                        else:
                            # The same object was updated
                            # FIXME This should have been automatic with `is_changed` flag in `state_`
                            item.state_.mark_changed()

                        to_cls_repo._dao.save(item)
                    elif entity._temp_cache[field_name]["change"] == "DELETED":
                        to_cls_repo._dao.delete(
                            entity._temp_cache[field_name]["old_value"]
                        )

                    # Reset temporary fields after processing
                    entity._temp_cache[field_name]["change"] = None
                    entity._temp_cache[field_name]["old_value"] = None

    def get(self, identifier) -> Union[BaseAggregate, BaseEntity, BaseView]:
        """This is a utility method to fetch data from the persistence store by its key identifier. All child objects,
        including enclosed entities, are returned as part of this call.

        Returns the fetched object.

        All other data filtering capabilities can be implemented by using the underlying DAO's
        :meth:`BaseDAO.filter` method.

        Filter methods are typically implemented as domain-contextual queries, like `find_adults()`,
        `find_residents_of_area(zipcode)`, etc. It is also possible to make use of more complicated,
        domain-friendly design patterns like the `Specification` pattern.
        """
        item = self._dao.get(identifier)
        return item


def repository_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseRepository, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Repository `{element_cls.__name__}` should be associated with an Aggregate"
        )

    # FIXME Uncomment
    # if not issubclass(element_cls.meta_.part_of, BaseAggregate):
    #     raise IncorrectUsageError(
    #         {"_entity": [f"Repository `{element_cls.__name__}` can only be associated with an Aggregate"]}
    #     )

    # Ensure the value of `database` is among known databases
    if element_cls.meta_.database != "ALL" and element_cls.meta_.database not in [
        database.value for database in Database
    ]:
        raise IncorrectUsageError(
            f"Repository `{element_cls.__name__}` should be associated with a valid Database"
        )

    return element_cls
