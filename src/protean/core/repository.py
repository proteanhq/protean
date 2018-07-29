"""Abstract Repository Classes"""

from abc import ABCMeta
from abc import abstractmethod


class Repository(metaclass=ABCMeta):
    """Repository interface to interact with databases"""

    @abstractmethod
    def query(self):
        """Query for Record(s)"""

    @abstractmethod
    def get(self):
        """Get a specific Record"""

    @abstractmethod
    def create(self):
        """Create a new Record"""

    @abstractmethod
    def update(self):
        """Update a Record"""

    @abstractmethod
    def delete(self, identifier):
        """Delete a Record"""
