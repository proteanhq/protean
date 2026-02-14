"""Simple field factory functions returning FieldSpec instances.

Each function is a thin wrapper around ``FieldSpec`` that pre-fills the
``python_type`` and type-specific defaults.  Users write::

    name = String(max_length=100, required=True)
    price = Float(min_value=0)

and the framework translates these into Pydantic-compatible annotations
during class creation.
"""

from __future__ import annotations

import datetime
from typing import Any

from protean.fields.spec import FieldSpec


# ---------------------------------------------------------------------------
# Simple field factories
# ---------------------------------------------------------------------------
def String(
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


def Text(sanitize: bool = True, **kwargs: Any) -> FieldSpec:
    """An unbounded text field (maps to ``sa.Text`` in SQLAlchemy).

    Like ``String`` but without a ``max_length`` constraint.
    """
    return FieldSpec(str, field_kind="text", sanitize=sanitize, **kwargs)


def Integer(
    min_value: int | None = None,
    max_value: int | None = None,
    **kwargs: Any,
) -> FieldSpec:
    """An integer field with optional min/max constraints."""
    return FieldSpec(int, min_value=min_value, max_value=max_value, **kwargs)


def Float(
    min_value: float | None = None,
    max_value: float | None = None,
    **kwargs: Any,
) -> FieldSpec:
    """A floating-point field with optional min/max constraints."""
    return FieldSpec(float, min_value=min_value, max_value=max_value, **kwargs)


def Boolean(**kwargs: Any) -> FieldSpec:
    """A boolean field."""
    return FieldSpec(bool, **kwargs)


def Date(**kwargs: Any) -> FieldSpec:
    """A date field (``datetime.date``)."""
    return FieldSpec(datetime.date, **kwargs)


def DateTime(**kwargs: Any) -> FieldSpec:
    """A datetime field (``datetime.datetime``)."""
    return FieldSpec(datetime.datetime, **kwargs)


def Identifier(**kwargs: Any) -> FieldSpec:
    """Shorthand for ``String(identifier=True)``.

    Automatically generates a UUID string if no default is provided.
    """
    kwargs.setdefault("identifier", True)
    return FieldSpec(str, field_kind="identifier", **kwargs)


def Auto(
    increment: bool = False,
    identity_strategy: str | None = None,
    identity_function: str | None = None,
    identity_type: str | None = None,
    **kwargs: Any,
) -> FieldSpec:
    """Auto-generated identity field used internally.

    The ``increment`` flag is consumed by the memory adapter and DAO to
    decide auto-increment behavior.
    """
    kwargs["required"] = False
    kwargs["identifier"] = True
    spec = FieldSpec(str, field_kind="auto", **kwargs)
    # Store auto-specific metadata as private attributes
    spec._increment = increment
    spec._identity_strategy = identity_strategy
    spec._identity_function = identity_function
    spec._identity_type = identity_type
    return spec
