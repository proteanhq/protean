"""Container field factory functions (List, Dict) returning FieldSpec instances.

These work alongside the simple field factories in ``simple.py``.
"""

import types as _types
import typing
from typing import TYPE_CHECKING, Any, cast

from protean._deprecation import warn_deprecated
from protean.exceptions import ValidationError
from protean.fields.embedded import ValueObject as VODescriptor
from protean.fields.spec import FieldSpec

# Sentinel distinguishing "``pickled`` not passed" from an explicit
# ``pickled=False``, so the deprecation warning fires on any explicit use.
_PICKLED_UNSET: Any = object()


def List(  # pyright: ignore[reportRedeclaration]
    content_type: Any = None, pickled: Any = _PICKLED_UNSET, **kwargs: Any
) -> FieldSpec:
    """A list field.

    ``content_type`` can be:
    - A ``FieldSpec``: ``List(String(max_length=30))`` → ``list[str]``
    - A ``ValueObject`` descriptor: ``List(content_type=ValueObject(Addr))`` → ``list[dict]``
    - A plain type: ``List(int)`` → ``list[int]``
    - ``None``: ``List()`` → ``list`` (untyped)

    The ``pickled`` flag is a dead legacy parameter — it is accepted but never
    forwarded to the resulting ``FieldSpec`` and has no effect. It is deprecated
    and will be removed in v1.0.0.
    """
    if pickled is not _PICKLED_UNSET:
        warn_deprecated(
            "The `pickled` argument on `List`",
            removal="1.0.0",
            alternative="It has no effect.",
        )

    # If content_type is a FieldSpec factory function (e.g. ``Integer`` rather
    # than ``Integer()``), call it to obtain a FieldSpec instance.
    if callable(content_type) and not isinstance(
        content_type, (type, FieldSpec, VODescriptor)
    ):
        content_type = content_type()

    # Reject content types that don't make sense in a list (e.g. Auto)
    if isinstance(content_type, FieldSpec) and content_type.field_kind == "auto":
        raise ValidationError({"content_type": ["Content type not supported"]})

    if isinstance(content_type, FieldSpec):
        # Use the resolved type to preserve Literal/choices constraints.
        # Strip Optional wrapping since list elements don't need it.
        resolved = content_type.resolve_type()
        origin = typing.get_origin(resolved)
        if origin is _types.UnionType or origin is typing.Union:
            args = [a for a in typing.get_args(resolved) if a is not type(None)]
            inner_type = args[0] if args else content_type.python_type
        else:
            inner_type = resolved
    elif isinstance(content_type, VODescriptor):
        # ValueObject descriptors wrap a VO class; use the actual VO type
        # so Pydantic accepts VO instances directly.
        inner_type = content_type.value_object_cls
    elif content_type is not None:
        inner_type = content_type
    else:
        inner_type = Any

    python_type = list[inner_type]  # type: ignore[valid-type]

    # Lists default to empty list, not None
    if "default" not in kwargs and not kwargs.get("required", False):
        kwargs["default"] = list  # Will become default_factory=list

    return FieldSpec(python_type, content_type=content_type, **kwargs)


def Dict(  # pyright: ignore[reportRedeclaration]
    value_type: Any = None, **kwargs: Any
) -> FieldSpec:
    """A dict/JSON field.

    ``value_type`` types the dict's values; keys are always ``str``:
    - ``None``: ``Dict()`` → ``dict | list`` (untyped JSON — unchanged behavior)
    - A ``ValueObject`` descriptor: ``Dict(value_type=ValueObject(Addr))`` →
      ``dict[str, Addr]``, a ``code → value object`` map that reconstructs and
      validates each value.

    Use the untyped ``Dict()`` for loose JSON of primitives; the typed form is
    for value-object maps.
    """
    # Dicts default to empty dict, not None
    if "default" not in kwargs and not kwargs.get("required", False):
        kwargs["default"] = dict  # Will become default_factory=dict

    # Untyped JSON column (objects OR arrays) — unchanged legacy behavior.
    # ``dict | list`` is a ``types.UnionType`` accepted at runtime (FieldSpec
    # guards every python_type use with ``isinstance(..., type)``), but the
    # public ``FieldSpec.__init__`` still declares ``python_type: type``.
    # Cast until that exported signature is widened to ``type | UnionType``.
    if value_type is None:
        return FieldSpec(cast(type, dict | list), **kwargs)

    if not isinstance(value_type, VODescriptor):
        raise ValidationError(
            {
                "value_type": [
                    "value_type must be a ValueObject; use Dict() for untyped values"
                ]
            }
        )

    # ValueObject descriptors wrap a VO class (or a forward-ref string); use the
    # actual VO type so Pydantic accepts and reconstructs VO instances directly.
    python_type = dict[str, value_type.value_object_cls]

    return FieldSpec(python_type, content_type=value_type, **kwargs)


# ---------------------------------------------------------------------------
# TYPE_CHECKING overrides
# ---------------------------------------------------------------------------
if TYPE_CHECKING:

    def List(  # type: ignore[misc]
        content_type: Any = None, pickled: bool = ..., **kwargs: Any
    ) -> list[Any]: ...

    def Dict(  # type: ignore[misc]
        value_type: Any = None, **kwargs: Any
    ) -> dict[str, Any]: ...
