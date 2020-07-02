"""Utility module for Protean

Definitions/declaractions in this module should be independent of other modules,
to the maximum extent possible.
"""
# Standard Library Imports
import functools

from enum import Enum, auto


class IdentityStrategy(Enum):
    UUID = auto()
    DATABASE = auto()
    FUNCTION = auto()


class IdentityType(Enum):
    INTEGER = "INTEGER"
    STRING = "STRING"
    UUID = "UUID"


class Database(Enum):
    ELASTICSEARCH = "ELASTICSEARCH"
    MEMORY = "MEMORY"
    POSTGRESQL = "POSTGRESQL"
    SQLITE = "SQLITE"


class classproperty(object):
    def __init__(self, fget):
        self.fget = fget

    def __get__(self, owner_self, owner_cls):
        return self.fget(owner_cls)


def fully_qualified_name(cls):
    """Return Fully Qualified name along with module"""
    return ".".join([cls.__module__, cls.__name__])


def singleton(cls):
    """Make a class a Singleton class (only one instance)"""

    @functools.wraps(cls)
    def wrapper_singleton(*args, **kwargs):
        if not wrapper_singleton.instance:
            wrapper_singleton.instance = cls(*args, **kwargs)
        return wrapper_singleton.instance

    wrapper_singleton.instance = None
    return wrapper_singleton


def convert_str_values_to_list(value):
    if not value:
        return []
    elif isinstance(value, str):
        return [value]
    else:
        return list(value)
