"""Utility module for Protean

Definitions/declaractions in this module should be independent of other modules,
to the maximum extent possible.
"""
# Standard Library Imports
import functools
import logging

from enum import Enum, auto

# Protean
from protean.core.exceptions import IncorrectUsageError

logger = logging.getLogger("protean.utils")


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


class DomainObjects(Enum):
    AGGREGATE = "AGGREGATE"
    APPLICATION_SERVICE = "APPLICATION_SERVICE"
    COMMAND = "COMMAND"
    COMMAND_HANDLER = "COMMAND_HANDLER"
    DOMAIN_EVENT = "DOMAIN_EVENT"
    DOMAIN_SERVICE = "DOMAIN_SERVICE"
    EMAIL = "EMAIL"
    ENTITY = "ENTITY"
    MODEL = "MODEL"
    REPOSITORY = "REPOSITORY"
    SERIALIZER = "SERIALIZER"
    SUBSCRIBER = "SUBSCRIBER"
    VALUE_OBJECT = "VALUE_OBJECT"
    VIEW = "VIEW"


def derive_element_class(element_cls, base_cls):
    if not issubclass(element_cls, base_cls):
        try:
            new_dict = element_cls.__dict__.copy()
            new_dict.pop("__dict__", None)  # Remove __dict__ to prevent recursion

            element_cls = type(element_cls.__name__, (base_cls,), new_dict)
        except BaseException as exc:
            logger.debug("Error during Element registration:", repr(exc))
            raise IncorrectUsageError(
                "Invalid class {element_cls.__name__} for type {element_type.value}"
                " (Error: {exc})",
            )

    return element_cls
