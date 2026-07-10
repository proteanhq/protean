"""Simple field factory functions returning FieldSpec instances.

Each function is a thin wrapper around ``FieldSpec`` that pre-fills the
``python_type`` and type-specific defaults.  Users write::

    name: String(max_length=100, required=True)
    price: Float(min_value=0)

and the framework translates these into Pydantic-compatible annotations
during class creation.
"""

import datetime
import decimal
from collections.abc import Callable
from enum import Enum as _Enum
from typing import TYPE_CHECKING, Any

from protean.exceptions import IncorrectUsageError
from protean.fields.spec import FieldSpec


# ---------------------------------------------------------------------------
# Simple field factories
# ---------------------------------------------------------------------------
def String(  # pyright: ignore[reportRedeclaration]
    max_length: int = 255,
    min_length: int | None = None,
    sanitize: bool = True,
    **kwargs: Any,
) -> FieldSpec:
    """A string field with optional length constraints.

    Defaults: ``max_length=255``, ``sanitize=True``.
    """
    return FieldSpec(
        str,
        max_length=max_length,
        min_length=min_length,
        sanitize=sanitize,
        **kwargs,
    )


def Text(  # pyright: ignore[reportRedeclaration]
    sanitize: bool = True, **kwargs: Any
) -> FieldSpec:
    """An unbounded text field (maps to ``sa.Text`` in SQLAlchemy).

    Like ``String`` but without a ``max_length`` constraint.
    """
    return FieldSpec(str, field_kind="text", sanitize=sanitize, **kwargs)


def Integer(  # pyright: ignore[reportRedeclaration]
    min_value: int | None = None,
    max_value: int | None = None,
    **kwargs: Any,
) -> FieldSpec:
    """An integer field with optional min/max constraints."""
    return FieldSpec(int, min_value=min_value, max_value=max_value, **kwargs)


def Float(  # pyright: ignore[reportRedeclaration]
    min_value: float | None = None,
    max_value: float | None = None,
    **kwargs: Any,
) -> FieldSpec:
    """A floating-point field with optional min/max constraints."""
    return FieldSpec(float, min_value=min_value, max_value=max_value, **kwargs)


def Decimal(  # pyright: ignore[reportRedeclaration]
    min_value: decimal.Decimal | int | float | None = None,
    max_value: decimal.Decimal | int | float | None = None,
    precision: int | None = None,
    scale: int | None = None,
    **kwargs: Any,
) -> FieldSpec:
    """An exact decimal field backed by ``decimal.Decimal``.

    Use for money and other values where binary floating-point rounding is
    unacceptable. ``precision`` (total number of digits) and ``scale`` (digits
    after the decimal point) are optional; when set they map to
    ``NUMERIC(precision, scale)`` on SQL providers and are validated by Pydantic
    (``max_digits``/``decimal_places``). When omitted, the value is
    arbitrary-precision where the backend supports it. Values are string-encoded
    in JSON/event payloads, so there is no float round-trip.
    """
    return FieldSpec(
        decimal.Decimal,
        min_value=min_value,
        max_value=max_value,
        precision=precision,
        scale=scale,
        **kwargs,
    )


def Boolean(**kwargs: Any) -> FieldSpec:  # pyright: ignore[reportRedeclaration]
    """A boolean field."""
    return FieldSpec(bool, **kwargs)


def Date(**kwargs: Any) -> FieldSpec:  # pyright: ignore[reportRedeclaration]
    """A date field (``datetime.date``)."""
    return FieldSpec(datetime.date, **kwargs)


def DateTime(**kwargs: Any) -> FieldSpec:  # pyright: ignore[reportRedeclaration]
    """A datetime field (``datetime.datetime``)."""
    return FieldSpec(datetime.datetime, **kwargs)


def Identifier(  # pyright: ignore[reportRedeclaration]
    identifier: bool = False, **kwargs: Any
) -> FieldSpec:
    """A UUID-like string field.

    When ``identifier=True``, marks this field as the entity's identity
    and auto-generates a UUID if no default is provided.
    """
    kwargs["identifier"] = identifier
    return FieldSpec(str, field_kind="identifier", **kwargs)


def Auto(  # pyright: ignore[reportRedeclaration]
    increment: bool = False,
    identifier: bool = False,
    identity_strategy: str | None = None,
    identity_function: str | Callable[..., Any] | None = None,
    identity_type: str | None = None,
    **kwargs: Any,
) -> FieldSpec:
    """Auto-generated field for identifiers and auto-increment sequences.

    The ``increment`` flag is consumed by the memory adapter and DAO to
    decide auto-increment behavior.  Set ``identifier=True`` to mark
    this as the entity's identity field.
    """
    kwargs["required"] = False
    kwargs["identifier"] = identifier
    # Auto-increment fields store integers; non-increment fields (UUID
    # identity) store strings.
    python_type = int if increment else str
    spec = FieldSpec(python_type, field_kind="auto", **kwargs)
    # Store auto-specific metadata as private attributes
    spec._increment = increment
    spec._identity_strategy = identity_strategy
    spec._identity_function = identity_function
    spec._identity_type = identity_type
    return spec


def Status(  # pyright: ignore[reportRedeclaration]
    enum_cls: type,
    *,
    transitions: dict[Any, Any] | None = None,
    **kwargs: Any,
) -> FieldSpec:
    """A status field constrained to an Enum's values with optional transition enforcement.

    Requires an Enum class as the first argument.  Valid values are the
    Enum members' ``value`` attributes (via Pydantic ``Literal`` validation).

    When ``transitions`` is provided, the framework automatically prevents
    illegal state changes.  Only transitions defined in the map are allowed.
    States not appearing as keys are terminal (no outgoing transitions).

    Example::

        class OrderStatus(Enum):
            DRAFT = "DRAFT"
            PLACED = "PLACED"
            CONFIRMED = "CONFIRMED"

        status = Status(OrderStatus, transitions={
            OrderStatus.DRAFT: [OrderStatus.PLACED],
            OrderStatus.PLACED: [OrderStatus.CONFIRMED],
        })
    """
    if not (isinstance(enum_cls, type) and issubclass(enum_cls, _Enum)):
        raise IncorrectUsageError(
            "Status() requires an Enum class as the first argument"
        )

    # Normalize default if it's an Enum member
    if "default" in kwargs and isinstance(kwargs["default"], _Enum):
        kwargs["default"] = kwargs["default"].value

    return FieldSpec(
        str,
        field_kind="status",
        choices=enum_cls,
        transitions=transitions,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# TYPE_CHECKING overrides — static type checkers see resolved Python types
# instead of FieldSpec, matching what the mypy plugin does at analysis time.
# This enables Pylance's dataclass_transform (from Pydantic's BaseModel) to
# generate correct __init__ parameters for domain elements.
# ---------------------------------------------------------------------------
if TYPE_CHECKING:

    def String(  # type: ignore[misc]
        max_length: int = 255,
        min_length: int | None = None,
        sanitize: bool = True,
        **kwargs: Any,
    ) -> str: ...

    def Text(sanitize: bool = True, **kwargs: Any) -> str: ...  # type: ignore[misc]

    def Integer(  # type: ignore[misc]
        min_value: int | None = None,
        max_value: int | None = None,
        **kwargs: Any,
    ) -> int: ...

    def Float(  # type: ignore[misc]
        min_value: float | None = None,
        max_value: float | None = None,
        **kwargs: Any,
    ) -> float: ...

    def Decimal(  # type: ignore[misc]
        min_value: decimal.Decimal | int | float | None = None,
        max_value: decimal.Decimal | int | float | None = None,
        precision: int | None = None,
        scale: int | None = None,
        **kwargs: Any,
    ) -> decimal.Decimal: ...

    def Boolean(**kwargs: Any) -> bool: ...  # type: ignore[misc]

    def Date(**kwargs: Any) -> datetime.date: ...  # type: ignore[misc]

    def DateTime(**kwargs: Any) -> datetime.datetime: ...  # type: ignore[misc]

    def Identifier(identifier: bool = False, **kwargs: Any) -> str: ...  # type: ignore[misc]

    def Auto(  # type: ignore[misc]
        increment: bool = False,
        identifier: bool = False,
        identity_strategy: str | None = None,
        identity_function: str | Callable[..., Any] | None = None,
        identity_type: str | None = None,
        **kwargs: Any,
    ) -> str: ...

    def Status(  # type: ignore[misc]
        enum_cls: type,
        *,
        transitions: dict[Any, Any] | None = None,
        **kwargs: Any,
    ) -> str: ...
