"""The ``ChangePlan`` type — a serializable, previewable description of a change.

A :class:`ChangePlan` is an ordered list of operations that a command like
``add`` or an upgrade would make to a project: create a file, edit a file, or
patch config. A plan is inert data. Producing one makes no filesystem change; a
separate applier (a later epic) executes it.

The plan follows the IR serialization house style: frozen dataclasses serialized
by an explicit ``to_dict``/``from_dict`` JSON dump, with a version marker
(``plan_version``) carried on the serialized form. No pydantic here; pydantic is
reserved for domain elements.

Operations are a discriminated union tagged by a ``kind`` field:

- ``"create"`` (:class:`CreateFileOperation`) — a new file, carrying its whole
  ``content``.
- ``"edit"`` (:class:`EditFileOperation`) — an edit to an existing file, carried
  as a unified-diff string.
- ``"config"`` (:class:`ConfigOperation`) — a structured key-path set/merge over
  ``domain.toml``. Config is structured data, never a text diff.

Usage::

    from protean.scaffold import ChangePlan, CreateFileOperation

    plan = ChangePlan(
        operations=(
            CreateFileOperation(path="app/domain.py", content="from protean ..."),
        ),
        description="Scaffold the domain module",
    )
    payload = plan.to_json()
    restored = ChangePlan.from_json(payload)
    assert restored == plan
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PLAN_VERSION",
    "ChangePlan",
    "ConfigOperation",
    "CreateFileOperation",
    "EditFileOperation",
    "Operation",
]

# The version marker carried on every serialized plan. Bumped when the
# serialized shape changes incompatibly; a plan_version the code does not
# understand is rejected loudly by ``from_dict``. Kept in lock-step with the
# JSON Schema under ``schema/v<PLAN_VERSION>/schema.json``.
PLAN_VERSION = "0.1.0"

# Discriminator tags for the operation union. A serialized operation carries its
# tag under the ``kind`` key.
_KIND_CREATE = "create"
_KIND_EDIT = "edit"
_KIND_CONFIG = "config"

# Valid values for a config op's ``operation`` field.
_CONFIG_OPERATIONS = frozenset({"set", "merge"})


@dataclass(frozen=True)
class CreateFileOperation:
    """Create a new file at *path*, carrying its whole *content*."""

    path: str
    content: str
    kind: str = field(default=_KIND_CREATE, init=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict, tagged with ``kind``."""
        return {"kind": _KIND_CREATE, "path": self.path, "content": self.content}


@dataclass(frozen=True)
class EditFileOperation:
    """Edit an existing file at *path*, carried as a unified-diff string."""

    path: str
    diff: str
    kind: str = field(default=_KIND_EDIT, init=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict, tagged with ``kind``."""
        return {"kind": _KIND_EDIT, "path": self.path, "diff": self.diff}


@dataclass(frozen=True)
class ConfigOperation:
    """Set or merge a value at a key path in ``domain.toml``.

    Config is structured, never a text diff. ``key_path`` is the ordered
    sequence of key segments (e.g. ``("databases", "default", "provider")``),
    ``value`` is the JSON value to set or merge, and ``operation`` is ``"set"``
    or ``"merge"``.
    """

    key_path: tuple[str, ...]
    value: Any
    operation: str = "set"
    kind: str = field(default=_KIND_CONFIG, init=False)

    def __post_init__(self) -> None:
        if self.operation not in _CONFIG_OPERATIONS:
            raise ValueError(
                f"Invalid config operation: {self.operation!r}. "
                f"Must be one of: {', '.join(sorted(_CONFIG_OPERATIONS))}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict, tagged with ``kind``.

        ``key_path`` is a tuple in Python but serializes to a JSON array; it is
        restored to a tuple by :meth:`ChangePlan.from_dict`.
        """
        return {
            "kind": _KIND_CONFIG,
            "key_path": list(self.key_path),
            "value": self.value,
            "operation": self.operation,
        }


# The operation union. A plan holds an ordered tuple of these; an applier
# executes them in sequence.
Operation = CreateFileOperation | EditFileOperation | ConfigOperation


def _operation_from_dict(data: dict[str, Any]) -> Operation:
    """Reconstruct one operation from its serialized dict, dispatching on ``kind``.

    Raises :exc:`ValueError` on an unknown ``kind`` or a missing required field.
    """
    if "kind" not in data:
        raise ValueError("Operation is missing its 'kind' discriminator")
    kind = data["kind"]

    if kind == _KIND_CREATE:
        return CreateFileOperation(
            path=_require(data, "path", kind),
            content=_require(data, "content", kind),
        )
    if kind == _KIND_EDIT:
        return EditFileOperation(
            path=_require(data, "path", kind),
            diff=_require(data, "diff", kind),
        )
    if kind == _KIND_CONFIG:
        key_path = _require(data, "key_path", kind)
        if not isinstance(key_path, list) or not all(
            isinstance(seg, str) for seg in key_path
        ):
            raise ValueError(
                "config operation 'key_path' must be a list of string segments"
            )
        # ``value`` is required but may legitimately be null/false/0, so check
        # for presence rather than truthiness.
        if "value" not in data:
            raise ValueError("config operation is missing required field 'value'")
        return ConfigOperation(
            key_path=tuple(key_path),
            value=data["value"],
            operation=data.get("operation", "set"),
        )

    raise ValueError(f"Unknown operation kind: {kind!r}")


def _require(data: dict[str, Any], key: str, kind: str) -> Any:
    """Return ``data[key]`` or raise a clear :exc:`ValueError` naming *kind*."""
    if key not in data:
        raise ValueError(f"{kind!r} operation is missing required field {key!r}")
    return data[key]


@dataclass(frozen=True)
class ChangePlan:
    """An ordered, serializable description of a change.

    Attributes
    ----------
    operations:
        The operations to apply, in order. An applier executes them in
        sequence, so position is semantic.
    description:
        An optional human-readable summary of the plan.
    """

    operations: tuple[Operation, ...] = ()
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-ready dict, carrying the ``plan_version`` marker."""
        result: dict[str, Any] = {
            "plan_version": PLAN_VERSION,
            "operations": [op.to_dict() for op in self.operations],
        }
        if self.description is not None:
            result["description"] = self.description
        return result

    def to_json(self, *, indent: int | None = None) -> str:
        """Serialize to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChangePlan:
        """Reconstruct a :class:`ChangePlan` from its serialized dict.

        Raises :exc:`ValueError` on a ``plan_version`` the code does not
        understand, on a missing ``operations`` list, on an unknown operation
        ``kind``, or on a missing required field. A corrupt or newer plan fails
        loud rather than parsing best-effort.
        """
        version = data.get("plan_version")
        if version != PLAN_VERSION:
            raise ValueError(
                f"Unsupported plan_version: {version!r}. "
                f"This build understands {PLAN_VERSION!r}."
            )

        raw_operations = data.get("operations")
        if not isinstance(raw_operations, list):
            raise ValueError("ChangePlan 'operations' must be a list")

        operations = tuple(_operation_from_dict(op) for op in raw_operations)

        description = data.get("description")
        if description is not None and not isinstance(description, str):
            raise ValueError("ChangePlan 'description' must be a string or omitted")

        return cls(operations=operations, description=description)

    @classmethod
    def from_json(cls, payload: str) -> ChangePlan:
        """Reconstruct a :class:`ChangePlan` from a JSON string.

        Raises :exc:`ValueError` on invalid JSON or a malformed plan.
        """
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid ChangePlan JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("A serialized ChangePlan must be a JSON object")
        return cls.from_dict(data)
