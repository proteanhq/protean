"""Read-only preview rendering for a :class:`~protean.scaffold.ChangePlan`.

:func:`render_preview` turns a plan into a human-readable summary of what would
change. It touches no files: every path is handled as a plain string, and the
renderer never opens, stats, or creates anything. The rendering is a separate
concern from an operation's representation — a create shows a header plus its
content, an edit shows its unified diff, and a config op shows ``key.path =
value  (set|merge)``.
"""

from __future__ import annotations

import json

from protean.scaffold.change_plan import (
    ChangePlan,
    ConfigOperation,
    CreateFileOperation,
    EditFileOperation,
    Operation,
)

__all__ = ["render_preview"]


def render_preview(plan: ChangePlan) -> str:
    """Render *plan* as a human-readable summary. Touches no files.

    An empty plan renders a single "no operations" line. Otherwise each
    operation is rendered as its own block, in plan order.
    """
    lines: list[str] = ["Change plan"]
    if plan.description is not None:
        lines.append(f"  {plan.description}")

    if not plan.operations:
        lines.append("")
        lines.append("(no operations)")
        return "\n".join(lines)

    for index, operation in enumerate(plan.operations, start=1):
        lines.append("")
        lines.extend(_render_operation(index, operation))

    return "\n".join(lines)


def _render_operation(index: int, operation: Operation) -> list[str]:
    """Render a single operation as a labelled block of lines."""
    if isinstance(operation, CreateFileOperation):
        return _render_create(index, operation)
    if isinstance(operation, EditFileOperation):
        return _render_edit(index, operation)
    if isinstance(operation, ConfigOperation):
        return _render_config(index, operation)
    # The union is closed; a new variant must add a branch here.
    raise ValueError(f"Cannot render unknown operation: {operation!r}")


def _render_create(index: int, operation: CreateFileOperation) -> list[str]:
    line_count = operation.content.count("\n") + 1 if operation.content else 0
    header = f"{index}. create {operation.path}  ({line_count} lines)"
    body = [f"    {line}" for line in operation.content.splitlines()]
    return [header, *body]


def _render_edit(index: int, operation: EditFileOperation) -> list[str]:
    header = f"{index}. edit {operation.path}"
    body = [f"    {line}" for line in operation.diff.splitlines()]
    return [header, *body]


def _render_config(index: int, operation: ConfigOperation) -> list[str]:
    key = ".".join(operation.key_path)
    value = json.dumps(operation.value)
    return [f"{index}. config {key} = {value}  ({operation.operation})"]
