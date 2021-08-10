"""Utility module for Protean

Definitions/declaractions in this module should be independent of other modules,
to the maximum extent possible.
"""
import functools
import logging

from enum import Enum, auto
from typing import Any, Tuple, Union
from uuid import uuid4

import pkg_resources

from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.globals import current_domain

logger = logging.getLogger("protean.utils")


class IdentityStrategy(Enum):
    UUID = auto()
    DATABASE = auto()
    FUNCTION = auto()


class IdentityType(Enum):
    INTEGER = "INTEGER"
    STRING = "STRING"
    UUID = "UUID"


class EventStrategy(Enum):
    DB_SUPPORTED = "DB_SUPPORTED"
    NAIVE = "NAIVE"


class EventExecution(Enum):
    THREADED = "THREADED"
    INLINE = "INLINE"


class CommandProcessingType(Enum):
    SYNC = "SYNC"
    ASYNC = "ASYNC"


class Database(Enum):
    ELASTICSEARCH = "ELASTICSEARCH"
    MEMORY = "MEMORY"
    POSTGRESQL = "POSTGRESQL"
    SQLITE = "SQLITE"


class Cache(Enum):
    MEMORY = "MEMORY"


def get_version():
    return pkg_resources.require("protean")[0].version


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
    EVENT = "EVENT"
    DOMAIN_SERVICE = "DOMAIN_SERVICE"
    EMAIL = "EMAIL"
    ENTITY = "ENTITY"
    MODEL = "MODEL"
    REPOSITORY = "REPOSITORY"
    SERIALIZER = "SERIALIZER"
    SUBSCRIBER = "SUBSCRIBER"
    VALUE_OBJECT = "VALUE_OBJECT"
    VIEW = "VIEW"


def derive_element_class(element_cls, base_cls, **opts):
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

    if callable(getattr(element_cls, "_extract_options", None)):
        element_cls._extract_options(**opts)

    return element_cls


def generate_identity():
    """Generate Unique Identifier, based on configured strategy"""
    if current_domain.config["IDENTITY_STRATEGY"] == IdentityStrategy.UUID.value:
        if current_domain.config["IDENTITY_TYPE"] == IdentityType.INTEGER.value:
            return uuid4().int
        elif current_domain.config["IDENTITY_TYPE"] == IdentityType.STRING.value:
            return str(uuid4())
        elif current_domain.config["IDENTITY_TYPE"] == IdentityType.UUID.value:
            return uuid4()
        else:
            raise ConfigurationError(
                f'Unknown Identity Type {current_domain.config["IDENTITY_TYPE"]}'
            )

    return None  # Database will generate the identity


def fetch_element_cls_from_registry(
    element: Union[str, Any], element_types: Tuple[DomainObjects, ...]
) -> Any:
    """Util Method to fetch an Element's class from its name"""
    if isinstance(element, str):
        try:
            # Try fetching by class name
            return current_domain._get_element_by_name(element_types, element).cls
        except ConfigurationError:
            try:
                # Try fetching by fully qualified class name
                return current_domain._get_element_by_fully_qualified_name(
                    element_types, element
                ).cls
            except AssertionError:
                # Element has not been registered
                # FIXME print a helpful debug message
                raise
    else:
        # FIXME Check if entity is subclassed from BaseEntity
        return element
