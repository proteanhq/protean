"""ResultSet Utility class and traversal methods for Repository results"""


class ResultSet(object):
    """Internal helper class returned by :meth:`Repository._read`
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
        """True if a previous page exists"""
        return bool(self.items) and self.offset > 0

    @property
    def has_next(self):
        """True if a next page exists."""
        return (self.offset + self.limit) < self.total

    @property
    def first(self):
        """Return the first item from the result"""
        if self.items:
            return self.items[0]
        else:
            return None

    def __bool__(self):
        """ Return true when the number of items is greater than 0"""
        if self.items:
            return True
        else:
            return False

    def __iter__(self):
        """ Return iterable on items """
        return iter(self.items)
