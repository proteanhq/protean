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


class RepositoryFactory(metaclass=ABCMeta):
    """Repository Factory interface to retrieve resource repositories"""

    def __init__(self, resource: str):
        """"Initialize repository factory"""
        self.resource = resource
        self.repo = self.get_repo(resource)

    @abstractmethod
    def get_repo(self, resource: str):
        """Retrieve repository for a given resource"""
