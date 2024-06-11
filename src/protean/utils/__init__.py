"""Utility module for Protean

Definitions/declaractions in this module should be independent of other modules,
to the maximum extent possible.
"""

import functools
import importlib
import logging

from datetime import UTC, datetime
from enum import Enum
from typing import Callable, Any
from uuid import uuid4

from protean.exceptions import ConfigurationError
from protean.globals import current_domain

logger = logging.getLogger(__name__)


class IdentityStrategy(Enum):
    UUID = "uuid"
    FUNCTION = "function"


class IdentityType(Enum):
    INTEGER = "integer"
    STRING = "string"
    UUID = "uuid"


class EventProcessing(Enum):
    SYNC = "sync"
    ASYNC = "async"


class CommandProcessing(Enum):
    SYNC = "sync"
    ASYNC = "async"


class Database(Enum):
    elasticsearch = "elasticsearch"
    memory = "memory"
    postgresql = "postgresql"
    sqlite = "sqlite"


class Cache(Enum):
    memory = "memory"
    redis = "redis"


class TypeMatcher:
    """Allow assertion on object type.

    Ex. mocked_object.assert_called_once_with(TypeMatcher(TargetCls))
    """

    def __init__(self, expected_type):
        self.expected_type = expected_type

    def __eq__(self, other):
        return isinstance(other, self.expected_type)


def utcnow_func():
    """Return the current time in UTC with timezone information"""
    return datetime.now(UTC)


def get_version():
    return importlib.metadata.version("protean")


def import_from_full_path(domain, path):
    spec = importlib.util.spec_from_file_location(domain, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    return getattr(mod, domain)


def fully_qualified_name(cls):
    """Return Fully Qualified name along with module"""
    return ".".join([cls.__module__, cls.__name__])


fqn = fully_qualified_name


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
    EVENT_HANDLER = "EVENT_HANDLER"
    EVENT_SOURCED_AGGREGATE = "EVENT_SOURCED_AGGREGATE"
    EVENT_SOURCED_REPOSITORY = "EVENT_SOURCED_REPOSITORY"
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
    from protean.container import Options

    if not issubclass(element_cls, base_cls):
        try:
            new_dict = element_cls.__dict__.copy()
            new_dict.pop("__dict__", None)  # Remove __dict__ to prevent recursion

            new_dict["meta_"] = Options(opts)

            element_cls = type(element_cls.__name__, (base_cls,), new_dict)
        except BaseException as exc:
            logger.debug("Error during Element registration:", repr(exc))
            raise
    else:
        element_cls.meta_ = Options(opts)

    # Assign default options for remaining items
    element_cls._set_defaults()

    return element_cls


def generate_identity(
    identity_strategy: str = None,
    identity_function: Callable[[], Any] | None = None,
    identity_type: str = None,
):
    """Generate Unique Identifier, based on configured strategy and type.

    If an identity type is provided, it will override the domain's configuration.
    """
    id_value = None

    # Consider strategy defined in the Auto field. If not provided, fall back to the
    #   domain's configuration.
    id_strategy = identity_strategy or current_domain.config["identity_strategy"]

    # UUID Strategy
    if id_strategy == IdentityStrategy.UUID.value:
        id_type = identity_type or current_domain.config["identity_type"]

        if id_type == IdentityType.INTEGER.value:
            id_value = uuid4().int
        elif id_type == IdentityType.STRING.value:
            id_value = str(uuid4())
        elif id_type == IdentityType.UUID.value:
            id_value = uuid4()
        else:
            raise ConfigurationError(f"Unknown Identity Type {id_type}")

    # Function Strategy
    elif id_strategy == IdentityStrategy.FUNCTION.value:
        # Run the function configured as part of the Auto field. If not provided, fall back
        #   to the function defined at the domain level.
        id_function = identity_function or current_domain._identity_function

        id_value = id_function()

    else:
        raise ConfigurationError(f"Unknown Identity Strategy {id_strategy}")

    return id_value


__all__ = [
    "Cache",
    "CommandProcessing",
    "Database",
    "DomainObjects",
    "EventProcessing",
    "IdentityStrategy",
    "IdentityType",
    "TypeMatcher",
    "convert_str_values_to_list",
    "derive_element_class",
    "fetch_element_cls_from_registry",
    "fully_qualified_name",
    "generate_identity",
    "get_version",
    "import_from_full_path",
    "singleton",
    "utcnow_func",
]
