""" Module containing Model related Class Definitions """

from abc import ABCMeta
from abc import abstractmethod


class BaseModel(metaclass=ABCMeta):
    """Model representing a schema in the database"""

    @classmethod
    @abstractmethod
    def from_entity(cls, entity):
        """Initialize Repository Model object from Entity object"""

    @classmethod
    @abstractmethod
    def to_entity(cls, *args, **kwargs):
        """Convert Repository Model Object to Entity Object"""
