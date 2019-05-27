from abc import ABC


class BaseRepository(ABC):
    """This class outlines the base repository functions,
    to be satisifed by all implementing repositories.

    It is also a marker interface for registering repository
    classes with the domain"""

    def __init__(self, dao):
        self.dao = dao

    def add(self, aggregate):
        """Add object to Repository"""

    def add_all(self, aggregates):
        """Add object to Repository"""

    def remove(self, aggregate):
        """Add object to Repository"""

    def remove_all(self, aggregates):
        """Add object to Repository"""
