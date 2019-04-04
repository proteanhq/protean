"""Classes and Functions for Lookup methods for Query translation"""
from abc import ABCMeta
from abc import abstractmethod


class BaseLookup(metaclass=ABCMeta):
    """Base Lookup class to implement in Adapters"""
    lookup_name = None

    def __init__(self, source, target):
        """Source is LHS and Target is RHS of a comparsion"""
        self.source, self.target = source, target

    def process_source(self):
        """Blank implementation; returns source"""
        return self.source

    def process_target(self):
        """Blank implementation; returns target"""
        return self.target

    @abstractmethod
    def as_expression(self):
        """To be implemented in each Adapter for its Lookups"""
        raise NotImplementedError
