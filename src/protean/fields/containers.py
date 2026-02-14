"""Container field factory functions (List, Dict) returning FieldSpec instances.

These work alongside the simple field factories in ``simple.py``.
"""

from __future__ import annotations

from typing import Any

from protean.fields.spec import FieldSpec


def List(content_type: Any = None, pickled: bool = False, **kwargs: Any) -> FieldSpec:
    """A list field.

    ``content_type`` can be:
    - A ``FieldSpec``: ``List(String(max_length=30))`` → ``list[str]``
    - A ``ValueObject`` descriptor: ``List(content_type=ValueObject(Addr))`` → ``list[dict]``
    - A plain type: ``List(int)`` → ``list[int]``
    - ``None``: ``List()`` → ``list`` (untyped)

    The ``pickled`` flag is a legacy parameter kept for backward compatibility.
    """
    from protean.exceptions import ValidationError
    from protean.fields.embedded import ValueObject as VODescriptor

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
        import types as _types
        import typing

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


def Dict(**kwargs: Any) -> FieldSpec:
    """A dict/JSON field.

    Accepts both ``dict`` and ``list`` values to support JSON columns that
    may store either objects or arrays.  Defaults to an empty dict if no
    default is provided.
    """
    # Dicts default to empty dict, not None
    if "default" not in kwargs and not kwargs.get("required", False):
        kwargs["default"] = dict  # Will become default_factory=dict

    return FieldSpec(dict | list, **kwargs)
