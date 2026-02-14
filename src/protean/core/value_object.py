"""Value Object Functionality and Classes"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError

from protean.exceptions import (
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.fields import Reference, ValueObject
from protean.fields.association import Association
from protean.utils import DomainObjects, _has_legacy_data_fields, derive_element_class
from protean.utils.container import BaseContainer, OptionsMixin, fields
from protean.utils.reflection import _FIELDS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Legacy BaseValueObject (old BaseContainer-based implementation)
# ---------------------------------------------------------------------------
class _LegacyBaseValueObject(BaseContainer, OptionsMixin):
    """Legacy BaseValueObject backed by BaseContainer and Protean field descriptors.

    This class preserves the original implementation for:
    - Internal VOs in eventing.py (MessageHeaders, Metadata, etc.)
    - VOs created dynamically by element_to_fact_event
    - VOs that use ValueObject embedding (VO-in-VO)
    - Any code still using old-style field descriptors (String, Float, etc.)
    """

    element_type = DomainObjects.VALUE_OBJECT

    def __new__(cls, *args, **kwargs):
        if cls is _LegacyBaseValueObject:
            raise NotSupportedError("_LegacyBaseValueObject cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        return [
            ("abstract", False),
            ("part_of", None),
        ]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()

        # Record invariant methods
        setattr(cls, "_invariants", defaultdict(dict))

        cls.__validate_for_basic_field_types()
        cls.__validate_for_non_identifier_fields()
        cls.__validate_for_non_unique_fields()

    @classmethod
    def __validate_for_basic_field_types(cls):
        for field_name, field_obj in fields(cls).items():
            # Value objects can hold all kinds of fields, except associations
            if isinstance(field_obj, (Reference, Association)):
                raise IncorrectUsageError(
                    f"Value Objects cannot have associations. "
                    f"Remove {field_name} ({field_obj.__class__.__name__}) from class {cls.__name__}"
                )

    @classmethod
    def __validate_for_non_identifier_fields(cls):
        for field_name, field_obj in fields(cls).items():
            if field_obj.identifier:
                raise IncorrectUsageError(
                    f"Value Objects cannot contain fields marked 'identifier' (field '{field_name}')"
                )

    @classmethod
    def __validate_for_non_unique_fields(cls):
        for field_name, field_obj in fields(cls).items():
            if field_obj.unique:
                raise IncorrectUsageError(
                    f"Value Objects cannot contain fields marked 'unique' (field '{field_name}')"
                )

    def __init__(self, *template, **kwargs):  # noqa: C901
        """Initialise the container.

        During initialization, set value on fields if validation passes.

        This initialization technique supports keyword arguments as well as dictionaries. You
            can even use a template for initial data.
        """

        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        self.errors = defaultdict(list)

        # Set the flag to prevent any further modifications
        self._initialized = False

        # Load the attributes based on the template
        loaded_fields = []
        for dictionary in template:
            if not isinstance(dictionary, dict):
                raise AssertionError(
                    f"Positional argument {dictionary} passed must be a dict. "
                    f"This argument serves as a template for loading common "
                    f"values.",
                )
            for field_name, val in dictionary.items():
                loaded_fields.append(field_name)
                setattr(self, field_name, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            loaded_fields.append(field_name)
            try:
                setattr(self, field_name, val)
            except ValidationError as err:
                for field_name in err.messages:
                    self.errors[field_name].extend(err.messages[field_name])

        # Load Value Objects from associated fields
        for field_name, field_obj in fields(self).items():
            if isinstance(field_obj, (ValueObject)) and not getattr(self, field_name):
                attrs = [
                    (embedded_field.field_name, embedded_field.attribute_name)
                    for embedded_field in field_obj.embedded_fields.values()
                ]
                values = {name: kwargs.get(attr) for name, attr in attrs}
                try:
                    value_object = field_obj.value_object_cls(**values)
                    # Set VO value only if the value object is not None/Empty
                    if value_object:
                        setattr(self, field_name, value_object)
                        loaded_fields.append(field_name)
                except ValidationError as err:
                    for sub_field_name in err.messages:
                        self.errors["{}_{}".format(field_name, sub_field_name)].extend(
                            err.messages[sub_field_name]
                        )

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name in fields(self):
            if field_name not in loaded_fields:
                setattr(self, field_name, None)

        self.defaults()

        if not self.errors:
            # `_postcheck()` will return a `defaultdict(list)` if errors are to be raised
            custom_errors = self._postcheck() or {}
            for field in custom_errors:
                self.errors[field].extend(custom_errors[field])

        # Raise any errors found during load
        if self.errors:
            logger.error(self.errors)
            raise ValidationError(self.errors)

        # If we made it this far, the Value Object is initialized
        #   and should be marked as such
        self._initialized = True

    def __setattr__(self, name, value):
        if not hasattr(self, "_initialized") or not self._initialized:
            return super().__setattr__(name, value)
        else:
            raise IncorrectUsageError(
                "Value Objects are immutable and cannot be modified once created"
            )

    def _postcheck(self):
        """Invariant checks performed after initialization"""
        errors = defaultdict(list)

        for invariant_method in self._invariants["post"].values():
            try:
                invariant_method(self)
            except ValidationError as err:
                for field_name in err.messages:
                    errors[field_name].extend(err.messages[field_name])

        return errors


# ---------------------------------------------------------------------------
# Pydantic Field Shim (compatibility bridge)
# ---------------------------------------------------------------------------
_SHIM_ERROR_MESSAGES: dict[str, str] = {
    "unique": "{entity_name} with {field_name} '{value}' is already present.",
    "required": "is required",
}


class _PydanticFieldShim:
    """Wraps a Pydantic FieldInfo to satisfy the FieldBase interface.

    This allows the reflection module (declared_fields, fields, attributes),
    the ValueObject embedding field (embedded.py), and the persistence layer
    (adapters, DAO) to work with Pydantic-based elements through the
    ``__container_fields__`` bridge.

    Attributes extracted from Pydantic's ``FieldInfo``:
    - ``required``: True when field has no default/default_factory
    - ``default``: default value (None if undefined)
    - ``max_length``: from ``annotated_types.MaxLen`` in metadata
    - ``min_value`` / ``max_value``: from ``Ge``/``Gt``/``Le``/``Lt``
    - ``identifier``: from ``json_schema_extra``
    - ``unique``: from ``json_schema_extra`` (True if identifier)
    - ``referenced_as``: from ``json_schema_extra``
    """

    def __init__(
        self, field_name: str, field_info: Any, python_type: type | None
    ) -> None:
        from pydantic_core import PydanticUndefined

        self.field_name = field_name
        self.attribute_name = field_name
        self._python_type = python_type
        self._field_info = field_info

        # Extract description from FieldInfo
        self.description: str | None = (
            getattr(field_info, "description", None) if field_info is not None else None
        )

        # Extract metadata from json_schema_extra if present
        extra = (
            getattr(field_info, "json_schema_extra", None) or {}
            if field_info is not None
            else {}
        )
        if isinstance(extra, dict):
            self.identifier = extra.get("identifier", False)
            self.referenced_as = extra.get("referenced_as")
            self.unique = extra.get("unique", False)
            self.increment = extra.get("increment", False)
        else:
            self.identifier = False
            self.referenced_as = None
            self.unique = False
            self.increment = False

        # Identifiers are always unique (matching legacy Field behavior)
        if self.identifier:
            self.unique = True

        if self.referenced_as:
            self.attribute_name = self.referenced_as

        # Extract required from FieldInfo
        self.required = field_info.is_required() if field_info is not None else False

        # Extract default from FieldInfo
        self.default = None
        if field_info is not None and field_info.default is not PydanticUndefined:
            self.default = field_info.default

        # Extract constraint metadata from FieldInfo.metadata
        self.max_length: int | None = None
        self.min_value: Any = None
        self.max_value: Any = None
        if field_info is not None:
            try:
                from annotated_types import Ge, Gt, Le, Lt, MaxLen
            except ImportError:  # pragma: no cover
                MaxLen = Ge = Gt = Le = Lt = None  # type: ignore[assignment,misc]

            if MaxLen is not None:
                for m in field_info.metadata:
                    if isinstance(m, MaxLen):
                        self.max_length = m.max_length
                    elif isinstance(m, Ge):
                        self.min_value = m.ge
                    elif isinstance(m, Gt):
                        self.min_value = m.gt
                    elif isinstance(m, Le):
                        self.max_value = m.le
                    elif isinstance(m, Lt):
                        self.max_value = m.lt

    @property
    def content_type(self) -> type | None:
        """For list[X] types, return the legacy field class for adapter compatibility.

        This allows the SQLAlchemy adapter to determine the correct ARRAY
        element type (e.g., list[int] → ARRAY(Integer)).
        """
        import types as _types
        import typing

        python_type = self._python_type

        # Unwrap Optional/Union: list[str] | None → list[str]
        origin = typing.get_origin(python_type)
        if origin is _types.UnionType or origin is typing.Union:
            args = [a for a in typing.get_args(python_type) if a is not type(None)]
            if args:
                python_type = args[0]
                origin = typing.get_origin(python_type)

        if origin is not list:
            return None

        type_args = typing.get_args(python_type)
        if not type_args:
            return None

        inner_type = type_args[0]

        # Lazy import to avoid circular dependency
        from protean.fields.basic import Boolean, Date, DateTime, Float, Integer, String

        from datetime import date as _date
        from datetime import datetime as _datetime

        _map: dict[type, type] = {
            str: String,
            int: Integer,
            float: Float,
            bool: Boolean,
            _datetime: DateTime,
            _date: Date,
        }
        return _map.get(inner_type)

    def as_dict(self, value: Any) -> Any:
        """Return JSON-compatible value of self."""
        from enum import Enum

        if value is None:
            return None
        # Prefer custom to_dict() over Pydantic model_dump() — our VOs
        # serialize datetime/nested types to JSON-compatible strings.
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, datetime):
            return str(value)
        if isinstance(value, Enum):
            return value.value
        # Handle lists/tuples of VOs or datetime values
        if isinstance(value, (list, tuple)):
            return [self.as_dict(item) for item in value]
        return value

    def get_attribute_name(self) -> str:
        return self.referenced_as or self.field_name

    def fail(self, key: str, **kwargs: Any) -> None:
        """Raise a ValidationError with a formatted message.

        Matches the ``Field.fail()`` interface used by
        ``BaseDAO._validate_unique()``.
        """
        msg = _SHIM_ERROR_MESSAGES.get(key, f"Validation failed: {key}")
        msg = msg.format(**kwargs)
        raise ValidationError({self.field_name: [msg]})


# ---------------------------------------------------------------------------
# Pydantic error conversion helper
# ---------------------------------------------------------------------------
def _convert_pydantic_errors(exc: PydanticValidationError) -> dict[str, list[str]]:
    """Convert Pydantic's ValidationError to Protean's {field: [messages]} format."""
    errors: dict[str, list[str]] = defaultdict(list)
    for error in exc.errors():
        field = str(error["loc"][0]) if error["loc"] else "_entity"
        msg = error["msg"]
        # Normalise Pydantic's "Field required" to the Protean-canonical
        # "is required" so that downstream assertions stay consistent
        # with the legacy field system.
        if msg == "Field required":
            msg = "is required"
        errors[field].append(msg)
    return dict(errors)


# ---------------------------------------------------------------------------
# New Pydantic-based BaseValueObject
# ---------------------------------------------------------------------------
class BaseValueObject(BaseModel, OptionsMixin):
    """Base class for Value Objects - immutable, no identity, equality by value.

    Uses Pydantic v2 BaseModel for field declaration, validation, and serialization.
    Fields are declared using standard Python type annotations with optional
    pydantic.Field constraints.
    """

    element_type: ClassVar[str] = DomainObjects.VALUE_OBJECT

    model_config = ConfigDict(extra="forbid")

    def __new__(cls, *args: Any, **kwargs: Any) -> BaseValueObject:
        if cls is BaseValueObject:
            raise NotSupportedError("BaseValueObject cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return [
            ("abstract", False),
            ("part_of", None),
        ]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        # Initialize invariant storage (model_fields is NOT yet populated here)
        setattr(cls, "_invariants", defaultdict(dict))
        # Set empty __container_fields__ as placeholder
        setattr(cls, _FIELDS, {})

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Called by Pydantic AFTER model_fields are fully populated."""
        super().__pydantic_init_subclass__(**kwargs)

        # Build __container_fields__ bridge from Pydantic model_fields
        fields_dict: dict[str, _PydanticFieldShim] = {}
        for fname, finfo in cls.model_fields.items():
            fields_dict[fname] = _PydanticFieldShim(fname, finfo, finfo.annotation)
        setattr(cls, _FIELDS, fields_dict)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Support template dict pattern: VO({"key": "val"}, key2="val2")
        if args:
            for template in args:
                if not isinstance(template, dict):
                    raise AssertionError(
                        f"Positional argument {template} passed must be a dict. "
                        f"This argument serves as a template for loading common "
                        f"values.",
                    )
                kwargs.update(template)
        try:
            super().__init__(**kwargs)
        except PydanticValidationError as e:
            raise ValidationError(_convert_pydantic_errors(e))

    def model_post_init(self, __context: Any) -> None:
        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        # Discover invariants from MRO (supports VOs used without domain registration)
        self._discover_invariants()

        self.defaults()

        errors = self._run_invariants("post")
        if errors:
            raise ValidationError(errors)

        object.__setattr__(self, "_initialized", True)

    def _discover_invariants(self) -> None:
        """Scan class MRO for @invariant decorated methods and register them."""
        for klass in type(self).__mro__:
            for name, attr in vars(klass).items():
                if callable(attr) and hasattr(attr, "_invariant"):
                    self._invariants[attr._invariant][name] = attr

    def __setattr__(self, name: str, value: Any) -> None:
        if not getattr(self, "_initialized", False):
            super().__setattr__(name, value)
        else:
            raise IncorrectUsageError(
                "Value Objects are immutable and cannot be modified once created"
            )

    def defaults(self) -> None:
        """Placeholder for defaults. Override in subclass when
        an attribute's default depends on other attribute values."""

    def _run_invariants(self, stage: str) -> dict[str, list[str]]:
        """Run invariants for a given stage. Return errors dict or empty."""
        errors: dict[str, list[str]] = defaultdict(list)

        for invariant_method in self._invariants.get(stage, {}).values():
            try:
                invariant_method(self)
            except ValidationError as err:
                for field_name in err.messages:
                    errors[field_name].extend(err.messages[field_name])

        return dict(errors) if errors else {}

    def _postcheck(self) -> dict[str, list[str]]:
        """Invariant checks performed after initialization.

        Returns a dict of errors (possibly empty) for compatibility with
        entity invariant runner (entity.py _run_invariants).
        """
        return self._run_invariants("post")

    def to_dict(self) -> dict[str, Any]:
        """Return data as a dictionary."""
        result: dict[str, Any] = {}
        for fname, shim in getattr(self, _FIELDS, {}).items():
            result[fname] = shim.as_dict(getattr(self, fname, None))
        return result

    def __eq__(self, other: object) -> bool:
        if type(other) is not type(self):
            return False
        return self.to_dict() == other.to_dict()

    def __hash__(self) -> int:
        return hash(frozenset(self.to_dict().items()))

    def __repr__(self) -> str:
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self) -> str:
        return "%s object (%s)" % (
            self.__class__.__name__,
            "{}".format(self.to_dict()),
        )

    def __bool__(self) -> bool:
        return any(
            bool(getattr(self, field_name, None))
            for field_name in getattr(self, _FIELDS, {})
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def value_object_factory(element_cls: type, domain: Any, **opts: Any) -> type:
    # Determine the correct base class:
    # 1. Explicit Pydantic inheritance → Pydantic
    # 2. Already inherits from legacy base → Legacy
    # 3. Has legacy data fields (String, Integer, etc.) → Legacy
    # 4. Otherwise (annotation-based or empty) → Pydantic
    if issubclass(element_cls, BaseValueObject):
        base_cls = BaseValueObject
    elif issubclass(element_cls, _LegacyBaseValueObject):
        base_cls = _LegacyBaseValueObject
    elif _has_legacy_data_fields(element_cls):
        base_cls = _LegacyBaseValueObject
    else:
        base_cls = BaseValueObject

    element_cls = derive_element_class(element_cls, base_cls, **opts)

    # Discover invariant methods using MRO scan (avoids inspect.getmembers deprecation warnings)
    for klass in element_cls.__mro__:
        for method_name, method in vars(klass).items():
            if (
                not (method_name.startswith("__") and method_name.endswith("__"))
                and callable(method)
                and hasattr(method, "_invariant")
            ):
                element_cls._invariants[method._invariant][method_name] = method

    return element_cls
