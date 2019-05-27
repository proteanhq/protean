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

    def remove(self, aggregate):
        """Remove object to Repository"""

    def get(self, identifier):
        """Retrieve object from Repository"""

    def filter(self, specification):
        """Filter for objects that fit specification"""
