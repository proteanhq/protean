"""Container field factory functions (List, Dict) returning FieldSpec instances.

These work alongside the simple field factories in ``simple.py``.
"""

from __future__ import annotations

from typing import Any

from protean.fields.spec import FieldSpec


def List(content_type: Any = None, **kwargs: Any) -> FieldSpec:
    """A list field.

    ``content_type`` can be:
    - A ``FieldSpec``: ``List(String(max_length=30))`` → ``list[str]``
    - A plain type: ``List(int)`` → ``list[int]``
    - ``None``: ``List()`` → ``list`` (untyped)
    """
    if isinstance(content_type, FieldSpec):
        inner_type = content_type.python_type
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
    """A dict field.

    Defaults to an empty dict if no default is provided.
    """
    # Dicts default to empty dict, not None
    if "default" not in kwargs and not kwargs.get("required", False):
        kwargs["default"] = dict  # Will become default_factory=dict

    return FieldSpec(dict, **kwargs)
