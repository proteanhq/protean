"""QuerySet Implementation"""

import logging
from typing import Any
from typing import Union

from protean.core.repository import repo_factory
from protean.utils.query import Q

logger = logging.getLogger('protean.core.entity')


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

    def __init__(self, entity_cls, criteria=None, offset: int = 0, limit: int = 10,
                 order_by: set = None):
        """Initialize either with empty preferences (when invoked on an Entity)
            or carry forward filters and preferences when chained
        """

        self._entity_cls = entity_cls
        self._criteria = criteria or Q()
        self._result_cache = None
        self._offset = offset or 0
        self._limit = limit or 10

        # `order_by` could be empty, or a string or a set.
        #   Intialize empty set if `order_by` is None
        #   Convert string to set if `order_by` is a String
        #   Safe-cast set to a set if `order_by` is already a set
        if order_by:
            self._order_by = set([order_by]) if isinstance(order_by, str) else set(order_by)
        else:
            self._order_by = set()

    def _clone(self):
        """
        Return a copy of the current QuerySet.
        """
        clone = self.__class__(self._entity_cls, criteria=self._criteria,
                               offset=self._offset, limit=self._limit,
                               order_by=self._order_by)
        return clone

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

    def order_by(self, order_by: Union[set, str]):
        """Update order_by setting for filter set"""
        clone = self._clone()
        if isinstance(order_by, str):
            order_by = {order_by}

        clone._order_by = clone._order_by.union(order_by)

        return clone

    def all(self):
        """Primary method to fetch data based on filters

        Also trigged when the QuerySet is evaluated by calling one of the following methods:
            * len()
            * bool()
            * list()
            * Iteration
            * Slicing
        """
        logger.debug(f'Query `{self.__class__.__name__}` objects with filters {self}')

        # Destroy any cached results
        self._result_cache = None

        # Fetch Model class and connected repository from Repository Factory
        model_cls = repo_factory.get_model(self._entity_cls)
        repository = repo_factory.get_repository(self._entity_cls)

        # order_by clause must be list of keys
        order_by = self._entity_cls.meta_.order_by if not self._order_by else self._order_by

        # Call the read method of the repository
        results = repository.filter(self._criteria, self._offset, self._limit, order_by)

        # Convert the returned results to entity and return it
        entity_items = []
        for item in results.items:
            entity = model_cls.to_entity(item)
            entity.state_.mark_retrieved()
            entity_items.append(entity)
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
                item.update(*data, **kwargs)
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
        logger.debug(f'Query `{self.__class__.__name__}` objects with raw query {query}')

        # Destroy any cached results
        self._result_cache = None

        # Fetch Model class and connected repository from Repository Factory
        model_cls = repo_factory.get_model(self._entity_cls)
        repository = repo_factory.get_repository(self._entity_cls)

        try:
            # Call the raw method of the repository
            results = repository.raw(query, data)

            # Convert the returned results to entity and return it
            entity_items = []
            for item in results.items:
                entity = model_cls.to_entity(item)
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
        # Fetch Model class and connected repository from Repository Factory
        deleted_item_count = 0
        try:
            items = self.all()

            for item in items:
                item.delete()
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

        repository = repo_factory.get_repository(self._entity_cls)

        try:
            updated_item_count = repository.update_all(self._criteria, *args, **kwargs)
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
        repository = repo_factory.get_repository(self._entity_cls)
        try:
            deleted_item_count = repository.delete_all(self._criteria)
        except Exception:
            # FIXME Log Exception
            raise

        return deleted_item_count

    ###############################
    # Python Magic method support #
    ###############################

    def __iter__(self):
        """Return results on iteration"""
        if self._result_cache:
            return iter(self._result_cache)

        return iter(self.all())

    def __len__(self):
        """Return length of results"""
        if self._result_cache:
            return self._result_cache.total

        return self.all().total

    def __bool__(self):
        """Return True if query results have items"""
        if self._result_cache:
            return bool(self._result_cache)

        return bool(self.all())

    def __repr__(self):
        """Support friendly print of query criteria"""
        return ("<%s: entity: %s, criteria: %s, offset: %s, limit: %s, order_by: %s>" %
                (self.__class__.__name__, self._entity_cls,
                 self._criteria.deconstruct(),
                 self._offset, self._limit, self._order_by))

    def __getitem__(self, k):
        """Support slicing of results"""
        if self._result_cache:
            return self._result_cache.items[k]

        return self.all().items[k]

    #########################
    # Result properties #
    #########################

    @property
    def total(self):
        """Return the total number of records"""
        if self._result_cache:
            return self._result_cache.total

        return self.all().total

    @property
    def items(self):
        """Return result values"""
        if self._result_cache:
            return self._result_cache.items

        return self.all().items

    @property
    def first(self):
        """Return the first result"""
        if self._result_cache:
            return self._result_cache.first

        return self.all().first

    @property
    def has_next(self):
        """Return True if there are more values present"""
        if self._result_cache:
            return self._result_cache.has_next

        return self.all().has_next

    @property
    def has_prev(self):
        """Return True if there are previous values present"""
        if self._result_cache:
            return self._result_cache.has_prev

        return self.all().has_prev
