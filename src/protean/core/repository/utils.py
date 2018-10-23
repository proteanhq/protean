"""Utility classes and methods for Repository"""
from math import ceil


class Pagination(object):
    """Internal helper class returned by :meth:`Repository._read`
    """

    def __init__(self, page: int, per_page: int, total: int,
                 items: list):
        # the current page number (1 indexed)
        self.page = page
        # the number of items to be displayed on a page.
        self.per_page = per_page
        # the total number of items matching the query
        self.total = total
        # the items for the current page
        self.items = items

    @property
    def pages(self):
        """The total number of pages"""
        if self.per_page == 0 or self.total is None:
            pages = 0
        else:
            pages = int(ceil(self.total / float(self.per_page)))

        return pages

    @property
    def has_prev(self):
        """True if a previous page exists"""
        return self.page > 1

    @property
    def has_next(self):
        """True if a next page exists."""
        return self.page < self.pages

    @property
    def first(self):
        """Return the first item from the result"""
        if self.items:
            return self.items[0]
        else:
            return None
