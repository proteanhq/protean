"""ResolvedField — post-resolution field metadata wrapper.

After FieldSpec resolution and Pydantic class creation, each field's
``FieldInfo`` is wrapped in a ``ResolvedField`` to provide Protean's
field reflection interface (required, identifier, max_length, as_dict, etc.).

This is the counterpart to ``FieldSpec`` (pre-resolution, user intent):

    FieldSpec  →  Pydantic FieldInfo  →  ResolvedField
    (what you write)   (what Pydantic uses)   (what Protean introspects)

Adapters, reflection utilities (``declared_fields``, ``fields``,
``attributes``), the ValueObject embedding field, and the persistence
layer all consume ``ResolvedField`` instances via the
``__container_fields__`` dict.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from protean.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Error message templates for ResolvedField.fail()
# ---------------------------------------------------------------------------
_ERROR_MESSAGES: dict[str, str] = {
    "unique": "{entity_name} with {field_name} '{value}' is already present.",
    "required": "is required",
}


class ResolvedField:
    """Wraps a Pydantic FieldInfo to provide Protean's field reflection API.

    Created during ``__pydantic_init_subclass__()`` for every domain element
    (Aggregate, Entity, ValueObject, Command, Event, Projection).  Stored in
    ``__container_fields__`` (accessed via the ``_FIELDS`` constant).

    Attributes extracted from ``FieldInfo``:
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
            # FieldSpec-originated metadata
            self.sanitize = extra.get("sanitize", False)
            self.field_kind = extra.get("field_kind", "standard")
            self._validators = extra.get("_validators", [])
            self._error_messages = extra.get("_error_messages", {})
        else:
            self.identifier = False
            self.referenced_as = None
            self.unique = False
            self.increment = False
            self.sanitize = False
            self.field_kind = "standard"
            self._validators = []
            self._error_messages = {}

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
    def pickled(self) -> bool:
        """Legacy compatibility — FieldSpec fields are never pickled."""
        return False

    @property
    def content_type(self) -> type | None:
        """For list[X] types, return the inner Python type.

        This allows the SQLAlchemy adapter to determine the correct ARRAY
        element type (e.g., list[int] → int → ARRAY(Integer)).
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

        return type_args[0]

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
        msg = _ERROR_MESSAGES.get(key, f"Validation failed: {key}")
        msg = msg.format(**kwargs)
        raise ValidationError({self.field_name: [msg]})


# ---------------------------------------------------------------------------
# Pydantic error conversion helper
# ---------------------------------------------------------------------------
def convert_pydantic_errors(exc: PydanticValidationError) -> dict[str, list[str]]:
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
        # Strip Pydantic's "Value error, " prefix from custom validator messages
        elif msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        errors[field].append(msg)
    return dict(errors)
