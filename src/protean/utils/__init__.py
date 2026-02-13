"""Utility module for Protean

Definitions/declaractions in this module should be independent of other modules,
to the maximum extent possible.
"""

from __future__ import annotations

import importlib
import logging
import types
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


def _rebuild_function_with_new_class_cell(
    func: types.FunctionType | None,
    new_cls: type,
    original_cls: type,
) -> types.FunctionType | None:
    """Rebuild a function with its ``__class__`` cell repointed to *new_cls*.

    When Python compiles a method using zero-argument ``super()``, the compiler
    creates a ``__class__`` free variable referencing the class being defined
    (PEP 3135).  If the class is later recreated via ``type()``, the copied
    methods still hold closure cells pointing to the *original* class.  This
    helper creates a new function object with the corrected closure.

    Returns ``None`` if no change was needed.
    """
    if func is None or not isinstance(func, types.FunctionType):
        return None

    freevars = func.__code__.co_freevars
    if "__class__" not in freevars:
        return None

    closure = func.__closure__
    if (
        closure is None
    ):  # pragma: no cover – defensive; CPython always provides closure when freevars exist
        return None

    idx = freevars.index("__class__")

    try:
        current_value = closure[idx].cell_contents
    except ValueError:
        # Cell is empty.
        return None

    if current_value is not original_cls:
        return None

    # Build a new closure, replacing only the __class__ cell.
    new_closure = tuple(
        types.CellType(new_cls) if i == idx else cell for i, cell in enumerate(closure)
    )

    new_func = types.FunctionType(
        func.__code__,
        func.__globals__,
        func.__name__,
        func.__defaults__,
        new_closure,
    )
    new_func.__kwdefaults__ = func.__kwdefaults__
    new_func.__dict__.update(func.__dict__)
    new_func.__module__ = func.__module__
    new_func.__doc__ = func.__doc__
    new_func.__annotations__ = func.__annotations__

    # Update __qualname__ to reference the new class.
    old_qualname = func.__qualname__
    old_prefix = original_cls.__qualname__ + "."
    if old_qualname.startswith(old_prefix):
        new_func.__qualname__ = (
            new_cls.__qualname__ + "." + old_qualname[len(old_prefix) :]
        )
    else:
        new_func.__qualname__ = old_qualname

    return new_func


def _fix_function_class_cell(
    attr_value: object,
    new_cls: type,
    original_cls: type,
) -> object | None:
    """Fix ``__class__`` cell in a single class attribute.

    Handles plain functions, ``classmethod``, ``staticmethod``, and
    ``property`` descriptors.  Returns the fixed attribute, or ``None``
    if no change was needed.
    """
    # classmethod / staticmethod wrappers
    if isinstance(attr_value, (classmethod, staticmethod)):
        fixed = _rebuild_function_with_new_class_cell(
            attr_value.__func__, new_cls, original_cls
        )
        if fixed is not None:
            return type(attr_value)(fixed)  # re-wrap with same descriptor type
        return None

    # property descriptors
    if isinstance(attr_value, property):
        changed = False
        fget, fset, fdel = attr_value.fget, attr_value.fset, attr_value.fdel

        fixed_fget = _rebuild_function_with_new_class_cell(fget, new_cls, original_cls)
        if fixed_fget is not None:
            fget, changed = fixed_fget, True

        fixed_fset = _rebuild_function_with_new_class_cell(fset, new_cls, original_cls)
        if fixed_fset is not None:
            fset, changed = fixed_fset, True

        fixed_fdel = _rebuild_function_with_new_class_cell(fdel, new_cls, original_cls)
        if fixed_fdel is not None:
            fdel, changed = fixed_fdel, True

        if changed:
            return property(fget, fset, fdel, attr_value.__doc__)
        return None

    # Plain functions
    if isinstance(attr_value, types.FunctionType):
        return _rebuild_function_with_new_class_cell(attr_value, new_cls, original_cls)

    return None


def _rebind_class_cells(new_cls: type, original_cls: type) -> None:
    """Rebind ``__class__`` closure cells in methods after dynamic class creation.

    When a class is recreated via ``type()`` (as in ``derive_element_class`` or
    ``clone_class``), copied methods still hold ``__class__`` closure cells
    pointing to the *original* class.  This breaks zero-argument ``super()``
    (PEP 3135).  This function walks the new class's namespace and rewrites
    those cells to reference *new_cls*.
    """
    for attr_name in list(vars(new_cls)):
        attr_value = vars(new_cls)[attr_name]
        fixed = _fix_function_class_cell(attr_value, new_cls, original_cls)
        if fixed is not None:
            try:
                type.__setattr__(new_cls, attr_name, fixed)
            except (
                AttributeError,
                TypeError,
            ):  # pragma: no cover – guard for C-extension / read-only descriptors
                pass


def _has_legacy_data_fields(cls: type) -> bool:
    """Check if a class uses legacy data field descriptors (String, Integer, etc.).

    Returns True if the class has any attribute that is an instance of
    ``protean.fields.base.Field`` but is NOT a Reference or ValueObject
    (which are dual-compatible with both legacy and Pydantic classes).

    Association descriptors (HasMany, HasOne) inherit from ``Association``,
    not ``Field``, and are excluded automatically.
    """
    from protean.fields.association import Reference
    from protean.fields.base import Field as LegacyDataField
    from protean.fields.embedded import ValueObject

    for attr in cls.__dict__.values():
        if isinstance(attr, LegacyDataField) and not isinstance(
            attr, (Reference, ValueObject)
        ):
            return True
    return False


def _prepare_pydantic_namespace(
    new_dict: dict,
    base_cls: type,
    opts: dict,
) -> None:
    """Prepare a class namespace dict for dynamic Pydantic class creation.

    When ``derive_element_class`` routes a plain (non-Pydantic) class to a
    Pydantic base, the namespace must be adjusted:

    1. ``meta_`` must have a ``ClassVar`` annotation (Pydantic rejects
       non-annotated, non-ignored attributes).
    2. For entity/aggregate base classes: if no identifier field is declared
       and ``auto_add_id_field`` is not False, inject a Pydantic-compatible
       auto-id annotation + default.
    """
    from typing import Annotated, ClassVar, get_args, get_origin

    from pydantic import Field as PydanticField
    from pydantic.fields import FieldInfo

    from protean.utils.container import Options

    annots = new_dict.get("__annotations__", {}).copy()

    # 1. Annotate meta_ as ClassVar so Pydantic ignores it
    annots["meta_"] = ClassVar[Options]

    # 2. Auto-id injection for entity/aggregate types
    needs_identity = any(
        name == "auto_add_id_field" for name, _ in base_cls._default_options()
    )
    auto_add = opts.get("auto_add_id_field", True)

    if needs_identity and auto_add is not False:
        # Check if an identifier is already declared
        has_id = False
        for attr_name, annotation in annots.items():
            if attr_name.startswith("_"):
                continue

            # Check Annotated[type, Field(..., json_schema_extra={"identifier": True})]
            if get_origin(annotation) is Annotated:
                for arg in get_args(annotation)[1:]:
                    if isinstance(arg, FieldInfo):
                        extra = getattr(arg, "json_schema_extra", None) or {}
                        if isinstance(extra, dict) and extra.get("identifier"):
                            has_id = True
                            break
            if has_id:
                break

            # Check direct default: field_name = Field(json_schema_extra={"identifier": True})
            attr_val = new_dict.get(attr_name)
            if isinstance(attr_val, FieldInfo):
                extra = getattr(attr_val, "json_schema_extra", None) or {}
                if isinstance(extra, dict) and extra.get("identifier"):
                    has_id = True
                    break

        if not has_id:
            annots["id"] = str
            new_dict["id"] = PydanticField(
                default_factory=lambda: str(uuid4()),
                json_schema_extra={"identifier": True},
            )

    new_dict["__annotations__"] = annots


def derive_element_class(
    element_cls: Type[Element] | Type[Any],
    base_cls: Type[Element],
    **opts: dict[str, str | bool],
) -> Type[Element]:
    from pydantic import BaseModel

    from protean.utils.container import Options

    # Ensure options being passed in are known
    known_options = [name for (name, _) in base_cls._default_options()]
    if not all(opt in known_options for opt in opts):
        raise ConfigurationError(f"Unknown option(s) {set(opts) - set(known_options)}")

    if not issubclass(element_cls, base_cls):
        try:
            original_cls = element_cls

            new_dict = element_cls.__dict__.copy()
            new_dict.pop("__dict__", None)  # Remove __dict__ to prevent recursion

            new_dict["meta_"] = Options(opts)

            # When routing to a Pydantic base, prepare the namespace so that
            # Pydantic's ModelMetaclass can process it correctly.
            if issubclass(base_cls, BaseModel):
                _prepare_pydantic_namespace(new_dict, base_cls, opts)

            element_cls = type(element_cls.__name__, (base_cls,), new_dict)

            # Fix zero-argument super() calls: rebind __class__ closure cells
            # from original_cls to the newly created element_cls (PEP 3135).
            _rebind_class_cells(element_cls, original_cls)
        except BaseException as exc:
            logger.debug("Error during Element registration: %s", repr(exc))
            raise
    else:
        element_cls.meta_ = Options(opts)

        # For Pydantic-based elements that explicitly inherit from the base,
        # ensure meta_ has a ClassVar annotation so that Pydantic ignores it
        # during clone_class and other dynamic class operations.
        if issubclass(base_cls, BaseModel):
            from typing import ClassVar

            annots = element_cls.__annotations__.copy()
            annots["meta_"] = ClassVar[Options]
            element_cls.__annotations__ = annots

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

    # For Pydantic models, creating a thin subclass is safer than
    # re-creating the class from __dict__.  Pydantic internalises field
    # defaults into model_fields during class creation, so a dict-copy
    # clone loses them.  A subclass inherits everything through the MRO.
    from pydantic import BaseModel

    if isinstance(cls, type) and issubclass(cls, BaseModel):
        new_cls = type(type(cls))(new_name, (cls,), {"__annotations__": {}})
        new_cls.__qualname__ = new_name
        return new_cls

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

    # Fix zero-argument super() calls: rebind __class__ closure cells
    # from the original cls to new_cls (PEP 3135).
    _rebind_class_cells(new_cls, cls)

    return new_cls


__all__ = [
    "_has_legacy_data_fields",
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
