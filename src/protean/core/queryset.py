"""QuerySet Implementation"""

from __future__ import annotations

import copy
import logging
from typing import TYPE_CHECKING, Any, Union

from protean.utils import DomainObjects
from protean.utils.globals import current_uow
from protean.utils.query import Q
from protean.utils.reflection import id_field

if TYPE_CHECKING:
    from protean.core.entity import BaseEntity
    from protean.domain import Domain
    from protean.port.dao import BaseDAO

logger = logging.getLogger(__name__)


class QuerySet:
    """A chainable class to gather a bunch of criteria and preferences (resultset size, order etc.)
    before execution.

    Internally, a QuerySet can be constructed, filtered, sliced, and generally passed around
    without actually fetching data. No data fetch actually occurs until you do something
    to evaluate the queryset.

    Once evaluated, a `QuerySet` typically caches its results. If the data in the database
    might have changed, you can get updated results for the same query by calling `all()` on a
    previously evaluated `QuerySet`.

    Attributes:
        offset: Number of records after which Results are fetched
        limit: The size the recordset to be pulled from database
        order_by: The list of parameters to be used for ordering the results.
            Use a `-` before the parameter name to sort in descending order
            and if not ascending order.
        excludes_: Objects with these properties will be excluded from the results
        filters: Filter criteria

    :return Returns a `ResultSet` object that holds the query results
    """

    def __init__(
        self,
        owner_dao: BaseDAO,
        domain: Domain,
        entity_cls: BaseEntity,
        criteria: Q = None,
        offset: int = 0,
        # Aggregates should be loaded in entirety
        # FIXME Should this limit be removed entirely?
        limit: int = 1000,
        order_by: list = None,
    ):
        """Initialize either with empty preferences (when invoked on an Entity)
        or carry forward filters and preferences when chained
        """
        self._owner_dao = owner_dao
        self._domain = domain
        self._entity_cls = entity_cls
        self._criteria = criteria or Q()
        self._result_cache = None
        self._offset = offset or 0
        self._limit = limit or 10

        # `order_by` could be empty, or a string or a list.
        #   Initialize empty list if `order_by` is None
        #   Convert string to list if `order_by` is a String
        #   Safe-cast list to a list if `order_by` is already a list
        if order_by:
            self._order_by = [order_by] if isinstance(order_by, str) else order_by
        else:
            self._order_by = []

    def _clone(self):
        """
        Return a copy of the current QuerySet.
        """
        clone = self.__class__(
            self._owner_dao,
            self._domain,
            self._entity_cls,
            criteria=self._criteria,
            offset=self._offset,
            limit=self._limit,
            order_by=self._order_by,
        )
        return clone

    #########################
    # Query support methods #
    #########################

    def _add_q(self, q_object):
        """Add a Q-object to the current filter."""
        self._criteria = self._criteria._combine(q_object, q_object.connector)

    def filter(self, *args, **kwargs):
        """
        Return a new QuerySet instance with the args ANDed to the existing
        set.
        """
        return self._filter_or_exclude(False, *args, **kwargs)

    def exclude(self, *args, **kwargs):
        """
        Return a new QuerySet instance with NOT (args) ANDed to the existing
        set.
        """
        return self._filter_or_exclude(True, *args, **kwargs)

    def _filter_or_exclude(self, negate, *args, **kwargs):
        clone = self._clone()
        if negate:
            clone._add_q(~Q(*args, **kwargs))
        else:
            clone._add_q(Q(*args, **kwargs))
        return clone

    def limit(self, limit):
        """Limit number of records"""
        clone = self._clone()

        if isinstance(limit, int):
            clone._limit = limit

        return clone

    def offset(self, offset):
        """Fetch results after `offset` value"""
        clone = self._clone()

        if isinstance(offset, int):
            clone._offset = offset

        return clone

    def order_by(self, order_by: Union[list, str]):
        """Update order_by setting for filter set"""
        clone = self._clone()
        if isinstance(order_by, str):
            order_by = [order_by]

        clone._order_by.extend(item for item in order_by if item not in clone._order_by)

        return clone

    def all(self) -> ResultSet:
        """Primary method to fetch data based on filters

        Also trigged when the QuerySet is evaluated by calling one of the following methods:
            * len()
            * bool()
            * list()
            * Iteration
            * Slicing
        """
        logger.debug(f"Query `{self.__class__.__name__}` objects with filters {self}")

        # Destroy any cached results
        self._result_cache = None

        # Call the read method of the dao
        results = self._owner_dao._filter(
            self._criteria, self._offset, self._limit, self._order_by
        )

        # Convert the returned results to entity and return it
        entity_items = []
        for item in results.items:
            entity = self._owner_dao.model_cls.to_entity(item)
            entity.state_.mark_retrieved()

            # If we are dealing with an aggregate, we should also update the last event position
            #   to make use of optimistic concurrency control. This event version will be used
            #   to check for conflicts when the aggregate is updated.
            # FIXME: This concurrency control applies only when events are generated. We should
            #   ensure the same control is applied when aggregates are updated without events.
            if entity.element_type == DomainObjects.AGGREGATE:
                # Fetch and sync events version
                identifier = getattr(entity, id_field(entity).field_name)
                last_message = self._domain.event_store.store.read_last_message(
                    f"{entity.meta_.stream_category}-{identifier}"
                )
                if last_message:
                    entity._event_position = last_message.position

            entity_items.append(entity)

            # Track aggregate at the UoW level, to be able to perform actions on UoW commit,
            #   like persisting events raised by the aggregate.
            if current_uow and entity.element_type == DomainObjects.AGGREGATE:
                current_uow._add_to_identity_map(entity)

        results.items = entity_items

        # Cache results
        self._result_cache = results

        return results

    def update(self, *data, **kwargs):
        """Updates all objects with details given if they match a set of conditions supplied.

        This method updates each object individually, to fire callback methods and ensure
        validations are run.

        Returns the number of objects matched (which may not be equal to the number of objects
            updated if objects rows already have the new value).
        """
        updated_item_count = 0

        try:
            items = self.all()

            for item in items:
                self._owner_dao.update(item, *data, **kwargs)
                updated_item_count += 1
        except Exception:
            # FIXME Log Exception
            raise

        return updated_item_count

    def raw(self, query: Any, data: Any = None):
        """Runs raw query directly on the database and returns Entity objects

        Note that this method will raise an exception if the returned objects
            are not of the Entity type.

        `query` is not checked for correctness or validity, and any errors thrown by the plugin or
            database are passed as-is. Data passed will be transferred as-is to the plugin.

        All other query options like `order_by`, `offset` and `limit` are ignored for this action.
        """
        logger.debug(
            f"Query `{self.__class__.__name__}` objects with raw query {query}"
        )

        # Destroy any cached results
        self._result_cache = None

        try:
            # Call the raw method of the repository
            results = self._owner_dao._raw(query, data)

            # Convert the returned results to entity and return it
            entity_items = []
            for item in results.items:
                entity = self._owner_dao.model_cls.to_entity(item)
                entity.state_.mark_retrieved()
                entity_items.append(entity)
            results.items = entity_items

            # Cache results
            self._result_cache = results
        except Exception:
            # FIXME Log Exception
            raise

        return results

    def delete(self):
        """Deletes matching objects from the Repository

        Does not throw error if no objects are matched.

        Returns the number of objects matched (which may not be equal to the number of objects
            deleted if objects rows already have the new value).
        """
        # Fetch Model class and connected repository from Domain
        deleted_item_count = 0

        try:
            items = self.all()

            for item in items:
                self._owner_dao.delete(item)
                deleted_item_count += 1
        except Exception:
            # FIXME Log Exception
            raise

        return deleted_item_count

    def update_all(self, *args, **kwargs):
        """Updates all objects with details given if they match a set of conditions supplied.

        This method forwards filters and updates directly to the repository. It does not
        instantiate entities and it does not trigger Entity callbacks or validations.

        Update values can be specified either as a dict, or keyword arguments.

        Returns the number of objects matched (which may not be equal to the number of objects
            updated if objects rows already have the new value).
        """
        updated_item_count = 0

        try:
            updated_item_count = self._owner_dao._update_all(
                self._criteria, *args, **kwargs
            )
        except Exception:
            # FIXME Log Exception
            raise

        return updated_item_count

    def delete_all(self, *args, **kwargs):
        """Deletes objects that match a set of conditions supplied.

        This method forwards filters directly to the repository. It does not instantiate entities and
        it does not trigger Entity callbacks or validations.

        Returns the number of objects matched and deleted.
        """
        deleted_item_count = 0
        try:
            deleted_item_count = self._owner_dao._delete_all(self._criteria)
        except Exception:
            # FIXME Log Exception
            raise

        return deleted_item_count

    ###############################
    # Python Magic method support #
    ###############################

    @property
    def _data(self):
        active_data = self._result_cache if self._result_cache else self.all()
        temp_data = copy.deepcopy(active_data)

        return temp_data

    def __iter__(self):
        """Return results on iteration"""
        return iter(self._data)

    def __len__(self):
        """Return length of results"""
        return self._data.total

    def __bool__(self):
        """Return True if query results have items"""
        return bool(self._data)

    def __repr__(self):
        """Support friendly print of query criteria"""
        return "<%s: entity: %s, criteria: %s, offset: %s, limit: %s, order_by: %s>" % (
            self.__class__.__name__,
            self._entity_cls,
            self._criteria.deconstruct(),
            self._offset,
            self._limit,
            self._order_by,
        )

    def __getitem__(self, k):
        """Support slicing of results"""
        return self._data.items[k]

    def __contains__(self, k):
        """Support `in` operations"""
        return k.id in [item.id for item in self._data.items]

    #########################
    # Result properties #
    #########################

    @property
    def total(self):
        """Return the total number of records"""
        return self._data.total

    @property
    def items(self):
        """Return result values"""
        return self._data.items

    @property
    def first(self):
        """Return the first result"""
        return self._data.first

    @property
    def last(self):
        """Return the last result"""
        return self._data.last

    @property
    def has_next(self):
        """Return True if there are more values present"""
        return self._data.has_next

    @property
    def has_prev(self):
        """Return True if there are previous values present"""
        return self._data.has_prev


class ResultSet(object):
    """This is an internal helper class returned by DAO query operations.

    The purpose of this class is to prevent DAO-specific data structures from leaking into the domain layer.
    It can help check whether results exist, traverse the results, fetch the total number of items and also provide
    basic pagination support.
    """

    def __init__(self, offset: int, limit: int, total: int, items: list):
        # the current offset (zero indexed)
        self.offset = offset
        # the number of items to be fetched
        self.limit = limit
        # the total number of items matching the query
        self.total = total
        # the results
        self.items = items

    @property
    def has_prev(self):
        """Is `True` if the results are a subset of all results"""
        return bool(self.items) and self.offset > 0

    @property
    def has_next(self):
        """Is `True` if more pages exist"""
        return (self.offset + self.limit) < self.total

    @property
    def first(self):
        """Return the first item from results"""
        if self.items:
            return self.items[0]

    @property
    def last(self):
        """Return the last item from results"""
        if self.items:
            return self.items[-1]

    def __bool__(self):
        """Returns `True` when the resultset is not empty"""
        return bool(self.items)

    def __iter__(self):
        """Returns an iterable on items, to support traversal"""
        return iter(self.items)

    def __len__(self):
        """Returns number of items in the resultset"""
        return len(self.items)

    def __repr__(self):
        return f"<ResultSet: {len(self.items)} items>"

    def to_dict(self):
        """Return the resultset as a dictionary"""
        return {
            "offset": self.offset,
            "limit": self.limit,
            "total": self.total,
            "items": self.items,
        }
