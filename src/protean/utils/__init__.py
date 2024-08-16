"""Utility module for Protean

Definitions/declaractions in this module should be independent of other modules,
to the maximum extent possible.
"""

from __future__ import annotations

import importlib
import logging
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Optional, Type
from uuid import UUID, uuid4

from protean.exceptions import ConfigurationError
from protean.utils.globals import current_domain

if TYPE_CHECKING:
    from protean.utils.container import Element

logger = logging.getLogger(__name__)


class IdentityStrategy(Enum):
    UUID = "uuid"
    FUNCTION = "function"


class IdentityType(Enum):
    INTEGER = "integer"
    STRING = "string"
    UUID = "uuid"


class Processing(Enum):
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

    def __init__(self, expected_type: Type[Any]) -> None:
        self.expected_type = expected_type

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.expected_type)


def utcnow_func() -> datetime:
    """Return the current time in UTC with timezone information"""
    return datetime.now(UTC)


def get_version() -> str:
    return importlib.metadata.version("protean")


def fully_qualified_name(cls) -> str:
    """Return Fully Qualified name along with module"""
    return ".".join([cls.__module__, cls.__qualname__])


fqn = fully_qualified_name


def convert_str_values_to_list(value) -> list:
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
    EVENT_SOURCED_REPOSITORY = "EVENT_SOURCED_REPOSITORY"
    DOMAIN_SERVICE = "DOMAIN_SERVICE"
    EMAIL = "EMAIL"
    ENTITY = "ENTITY"
    MODEL = "MODEL"
    REPOSITORY = "REPOSITORY"
    SUBSCRIBER = "SUBSCRIBER"
    VALUE_OBJECT = "VALUE_OBJECT"
    VIEW = "VIEW"


def derive_element_class(
    element_cls: Type[Element] | Type[Any],
    base_cls: Type[Element],
    **opts: dict[str, str | bool],
) -> Type[Element]:
    from protean.utils.container import Options

    # Ensure options being passed in are known
    known_options = [name for (name, _) in base_cls._default_options()]
    if not all(opt in known_options for opt in opts):
        raise ConfigurationError(f"Unknown option(s) {set(opts) - set(known_options)}")

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
    identity_strategy: Optional[str] = None,
    identity_function: Callable[[], Any] | None = None,
    identity_type: Optional[str] = None,
) -> str | int | UUID:
    """Generate Unique Identifier, based on configured strategy and type.

    If an identity type is provided, it will override the domain's configuration.
    """
    id_value: Optional[str | int | UUID] = None

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
            raise ConfigurationError(f"Unknown Identity Type '{id_type}'")

    # Function Strategy
    elif id_strategy == IdentityStrategy.FUNCTION.value:
        # Run the function configured as part of the Auto field. If not provided, fall back
        #   to the function defined at the domain level.
        id_function = identity_function or current_domain._identity_function
        id_type = identity_type or current_domain.config["identity_type"]

        if callable(id_function):
            id_value = id_function()
        else:
            raise ConfigurationError("Identity function is invalid")

    else:
        raise ConfigurationError(f"Unknown Identity Strategy {id_strategy}")

    # This is a fallback, in case the identity generation fails
    if id_value is None:
        raise ConfigurationError("Failed to generate identity value")

    return id_value


__all__ = [
    "Cache",
    "convert_str_values_to_list",
    "Database",
    "derive_element_class",
    "DomainObjects",
    "fully_qualified_name",
    "generate_identity",
    "get_version",
    "IdentityStrategy",
    "IdentityType",
    "Processing",
    "TypeMatcher",
    "utcnow_func",
]
