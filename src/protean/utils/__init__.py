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
    DATABASE_MODEL = "DATABASE_MODEL"
    DOMAIN_SERVICE = "DOMAIN_SERVICE"
    EMAIL = "EMAIL"
    ENTITY = "ENTITY"
    EVENT = "EVENT"
    EVENT_HANDLER = "EVENT_HANDLER"
    EVENT_SOURCED_REPOSITORY = "EVENT_SOURCED_REPOSITORY"
    PROJECTION = "PROJECTION"
    PROJECTOR = "PROJECTOR"
    REPOSITORY = "REPOSITORY"
    SUBSCRIBER = "SUBSCRIBER"
    VALUE_OBJECT = "VALUE_OBJECT"


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


def clone_class(cls: Element, new_name: str) -> Type[Element]:
    """Clone a class with a new name.

    Creates a new class with the same attributes and behavior as the original,
    but with a different name. This is useful for creating variations of domain
    elements without deep copying instance attributes.

    Args:
        cls: The class to clone (must be an Element or its subclass)
        new_name: The name for the new class (must be a valid Python identifier)

    Returns:
        A new class type with the specified name

    Raises:
        TypeError: If cls is not a class or new_name is not a string
        ValueError: If new_name is not a valid Python identifier
    """
    if not isinstance(cls, type):
        raise TypeError(f"Expected a class, got {type(cls).__name__}")

    if not isinstance(new_name, str):
        raise TypeError(f"Class name must be a string, got {type(new_name).__name__}")

    if not new_name:
        raise ValueError("Class name cannot be empty")

    if not new_name.isidentifier():
        raise ValueError(f"'{new_name}' is not a valid Python identifier")

    # Import keyword module to check for reserved keywords
    import keyword

    if keyword.iskeyword(new_name):
        raise ValueError(f"'{new_name}' is a reserved Python keyword")

    # Collect attributes, excluding auto-generated and special ones
    # These should not be copied to avoid conflicts and maintain proper behavior
    excluded_attrs = {
        "__dict__",  # Instance attribute dictionary
        "__weakref__",  # Weak reference support
        "__module__",  # Will be set automatically by type()
        "__doc__",  # Will be inherited or can be set separately
        "__qualname__",  # Will be set explicitly below
    }

    # Create a shallow copy of class attributes, excluding the unwanted ones
    attrs = {}
    slots = getattr(cls, "__slots__", None)
    slot_names = set()

    # If the class has __slots__, collect slot names to avoid conflicts
    if slots is not None:
        if isinstance(slots, (tuple, list)):
            slot_names = set(slots)
        elif isinstance(slots, str):
            slot_names = {slots}

    for key, value in cls.__dict__.items():
        if key not in excluded_attrs:
            # Skip slot descriptors to avoid conflicts when cloning classes with __slots__
            if slots is not None and key in slot_names:
                # Skip the descriptor created by __slots__ to avoid conflicts
                continue
            attrs[key] = value

    # Create the new class using type(), preserving the metaclass
    # Pass the metaclass explicitly to preserve metaclass behavior
    metaclass = type(cls)
    if metaclass is not type:
        # Custom metaclass - preserve it
        new_cls = metaclass(new_name, cls.__bases__, attrs)
    else:
        # Standard type metaclass
        new_cls = type(new_name, cls.__bases__, attrs)

    # Set the qualified name to match the class name
    # This ensures proper representation in debugging and introspection
    new_cls.__qualname__ = new_name

    return new_cls


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
