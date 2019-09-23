# -*- coding: utf-8 -*-
"""
    protean.core.repository.base
    ~~~~~~~~~
    This module contains the definition of a Base Model class.

    :copyright: 2019 Protean
    :license: BSD-3-Clause
"""
# Standard Library Imports
from abc import ABCMeta, abstractmethod


class BaseModel(metaclass=ABCMeta):
    """This is a Model representing a data schema in the persistence store. A concrete implementation of this
    model has to be provided by each persistence store plugin.
    """

    @classmethod
    @abstractmethod
    def from_entity(cls, entity):
        """Initialize Repository Model object from Entity object"""

    @classmethod
    @abstractmethod
    def to_entity(cls, *args, **kwargs):
        """Convert Repository Model Object to Entity Object"""
