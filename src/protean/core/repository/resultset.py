# Standard Library Imports
import logging

logger = logging.getLogger("protean.repository")


class ResultSet(object):
    """This is an internal helper class returned by DAO query operations.

    The purpose of this class is to prevent DAO-specific data structures from leaking into the domain layer.
    It can help check whether results exist, traverse the results, fetch the total number of items and also provide
    basic pagination support.
    """

    def __init__(self, offset: int, limit: int, total: int, items: list):
        # the current offset (zero indexed)
        self.offset = offset
        # the number of items to be displayed on a page.
        self.limit = limit
        # the total number of items matching the query
        self.total = total
        # the items for the current page
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
        """Is the first item from results"""
        if self.items:
            return self.items[0]

    def __bool__(self):
        """Returns `True` when the resultset is not empty"""
        return bool(self.items)

    def __iter__(self):
        """Returns an iterable on items, to support traversal"""
        return iter(self.items)

    def __len__(self):
        """Returns number of items in the resultset"""
        return len(self.items)
