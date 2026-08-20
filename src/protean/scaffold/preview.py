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
    OWNERSHIP_GENERATED,
    OWNERSHIP_HAND_OWNED,
    ChangePlan,
    ConfigOperation,
    CreateFileOperation,
    EditFileOperation,
    Operation,
)

__all__ = ["render_preview"]

# How each ownership value reads in the preview. "generated" files a re-run of
# ``add`` refreshes; "hand-owned" files it leaves alone (the seam, ADR-0035).
# Both keys are present, so the lookup is direct: ``CreateFileOperation`` already
# rejects any other value, so there is no unknown case to fall back on.
_OWNERSHIP_LABELS = {
    OWNERSHIP_GENERATED: "generated",
    OWNERSHIP_HAND_OWNED: "hand-owned",
}


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
    # The union is closed; mypy narrows the remainder to ConfigOperation, so a new
    # variant must add a branch above or the type check fails.
    return _render_config(index, operation)


def _render_create(index: int, operation: CreateFileOperation) -> list[str]:
    body = [f"    {line}" for line in operation.content.splitlines()]
    label = _OWNERSHIP_LABELS[operation.ownership]
    header = f"{index}. create {operation.path}  ({len(body)} lines, {label})"
    return [header, *body]


def _render_edit(index: int, operation: EditFileOperation) -> list[str]:
    header = f"{index}. edit {operation.path}"
    body = [f"    {line}" for line in operation.diff.splitlines()]
    return [header, *body]


def _render_config(index: int, operation: ConfigOperation) -> list[str]:
    key = ".".join(operation.key_path)
    # sort_keys so a dict-valued config op renders the same way every time,
    # whatever order the producer built it in. Previews get diffed.
    value = json.dumps(operation.value, sort_keys=True)
    return [f"{index}. config {key} = {value}  ({operation.operation})"]
