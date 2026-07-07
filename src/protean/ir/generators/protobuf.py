"""Protocol Buffers (proto3) schema generator from IR field metadata.

Converts IR element dicts into ``.proto`` (proto3) source text.

Usage::

    from protean.ir.generators.protobuf import (
        generate_proto_schema,
        generate_proto_schemas,
    )

    proto_text = generate_proto_schema(element_ir, all_elements=flat_index)
    all_protos = generate_proto_schemas(ir)

Conventions:

- Each element becomes a proto3 ``message``; referenced value objects and
  entities become sibling messages in the same file.
- Optional fields use the proto3 ``optional`` label (explicit presence);
  list / has-many / value-object-list fields use ``repeated``.
- Date/DateTime map to the well-known ``google.protobuf.Timestamp``.
- **Field numbers are assigned 1..N in sorted field-name order.** This is
  deterministic, so re-generating the same schema always yields the same
  numbers. (Adding a new field can shift the numbers of alphabetically-later
  fields; preserving wire compatibility across such edits would need a persisted
  number map, which is out of scope for schema *emission*.)
- Output is deterministic and sorted.
"""

from __future__ import annotations

from typing import Any

from protean.ir.generators.base import module_path, short_name
from protean.ir.generators.schema import _build_flat_elements, iter_data_elements

_TIMESTAMP = "google.protobuf.Timestamp"

# IR scalar type → proto3 scalar type. Integers use int64 and floats double to
# avoid silently narrowing unbounded Python numbers. Both Date and DateTime map
# to the well-known ``google.protobuf.Timestamp``; a calendar-only Date is
# slightly lossy (Timestamp carries a time component), but the accurate
# ``google.type.Date`` lives in googleapis, not the well-known types, and is not
# worth that dependency for schema emission.
_TYPE_MAP: dict[str, str] = {
    "String": "string",
    "Text": "string",
    "Status": "string",
    "Identifier": "string",
    "Auto": "string",
    "Integer": "int64",
    "Float": "double",
    "Boolean": "bool",
    "Date": _TIMESTAMP,
    "DateTime": _TIMESTAMP,
}


def _scalar_proto_type(field: dict[str, Any]) -> str:
    ir_type = field.get("type", "")
    if field.get("kind") == "auto" or ir_type == "Auto":
        return "int64" if field.get("increment") else "string"
    return _TYPE_MAP.get(ir_type, "string")


def _field_proto_type(
    field: dict[str, Any],
    all_elements: dict[str, dict[str, Any]],
    referenced: set[str],
) -> tuple[str, bool]:
    """Return ``(proto_type, is_repeated)`` for an IR field.

    Referenced value-object/entity message names are collected in
    ``referenced`` so their message definitions get emitted in the same file.
    """
    kind = field.get("kind", "standard")

    if kind in ("value_object", "has_one"):
        return _referenced_message(field.get("target", ""), referenced), False
    if kind in ("value_object_list", "has_many"):
        return _referenced_message(field.get("target", ""), referenced), True
    if kind == "reference":
        return "string", False
    if kind == "list":
        content = field.get("content_type")
        return (_TYPE_MAP.get(content, "string") if content else "string"), True
    if kind == "dict":
        # proto3 map<string, string> is not "repeated"; represented specially.
        return "map<string, string>", False
    return _scalar_proto_type(field), False


def _referenced_message(target_fqn: str, referenced: set[str]) -> str:
    name = short_name(target_fqn)
    if not name:
        return "map<string, string>"
    referenced.add(target_fqn)
    return name


def _message_body(
    name: str,
    fields: dict[str, dict[str, Any]],
    all_elements: dict[str, dict[str, Any]],
    referenced: set[str],
) -> list[str]:
    """Render a single proto3 ``message`` block as a list of lines."""
    lines = [f"message {name} {{"]
    for number, (fname, fspec) in enumerate(sorted(fields.items()), start=1):
        proto_type, repeated = _field_proto_type(fspec, all_elements, referenced)
        is_required = fspec.get("required") or fspec.get("identifier")

        # `map` fields cannot carry a label; a repeated field never uses
        # `optional` (repeated already models absence as an empty list).
        if proto_type.startswith("map<"):
            label = ""
        elif repeated:
            label = "repeated "
        elif is_required:
            label = ""
        else:
            label = "optional "

        lines.append(f"  {label}{proto_type} {fname} = {number};")
    lines.append("}")
    return lines


def generate_proto_schema(
    element: dict[str, Any],
    *,
    all_elements: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Generate proto3 ``.proto`` source text for a single IR element."""
    flat = all_elements or {}
    name = element.get("name", "") or short_name(element.get("fqn", ""))
    namespace = module_path(element.get("fqn", "")) or "protean"

    referenced: set[str] = set()
    message_blocks: list[list[str]] = [
        _message_body(name, element.get("fields", {}), flat, referenced)
    ]

    # Emit referenced value-object / entity messages (deterministic order,
    # cycle-safe via a seen set).
    seen: set[str] = set()
    queue = sorted(referenced)
    while queue:
        target_fqn = queue.pop(0)
        ref_name = short_name(target_fqn)
        if ref_name in seen or ref_name == name:
            continue
        seen.add(ref_name)
        target = flat.get(target_fqn, {})
        nested_refs: set[str] = set()
        message_blocks.append(
            _message_body(ref_name, target.get("fields", {}), flat, nested_refs)
        )
        queue.extend(sorted(nested_refs))

    needs_timestamp = any(
        _TIMESTAMP in line for block in message_blocks for line in block
    )

    header = ['syntax = "proto3";', f"package {namespace};"]
    if needs_timestamp:
        header.append('import "google/protobuf/timestamp.proto";')

    parts = ["\n".join(header)]
    parts.extend("\n".join(block) for block in message_blocks)
    return "\n\n".join(parts) + "\n"


def generate_proto_schemas(ir: dict[str, Any]) -> dict[str, str]:
    """Generate ``.proto`` text for every data-carrying element in the IR."""
    flat = _build_flat_elements(ir)
    return {
        fqn: generate_proto_schema(element, all_elements=flat)
        for fqn, element in iter_data_elements(flat)
    }
