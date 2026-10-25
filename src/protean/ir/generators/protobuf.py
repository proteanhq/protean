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

- Each element becomes a proto3 ``message`` in its own file. When the caller
  passes ``import_path`` (the schema writer does), a file that references a
  value object or entity imports that element's file and names the type by its
  full name, ``.<package>.<Name>``. The leading dot makes ``protoc`` resolve
  the name from the root, so a package such as ``a.a.a`` cannot shadow it.
- Without ``import_path``, or for a target the lookup has no file for, the
  referenced value objects and entities become sibling messages in the same
  file, so a single file still compiles on its own.
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

from collections.abc import Callable
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
    "Decimal": "string",
    "Boolean": "bool",
    "Date": _TIMESTAMP,
    "DateTime": _TIMESTAMP,
}


def _scalar_proto_type(field: dict[str, Any]) -> str:
    ir_type = field.get("type", "")
    if field.get("kind") == "auto" or ir_type == "Auto":
        return "int64" if field.get("increment") else "string"
    return _TYPE_MAP.get(ir_type, "string")


# Resolves a referenced target fqn to the proto type name a field uses, and
# records in the given set any target that must be emitted as a sibling message.
_Resolver = Callable[[str, set[str]], str]


def _field_proto_type(
    field: dict[str, Any],
    resolve: _Resolver,
    referenced: set[str],
) -> tuple[str, bool]:
    """Return ``(proto_type, is_repeated)`` for an IR field.

    Value-object and entity targets go through ``resolve``, which either names
    an imported type or adds the target to ``referenced`` so its message
    definition gets emitted in the same file.
    """
    kind = field.get("kind", "standard")

    if kind in ("value_object", "has_one"):
        return resolve(field.get("target", ""), referenced), False
    if kind in ("value_object_list", "has_many"):
        return resolve(field.get("target", ""), referenced), True
    if kind == "reference":
        return "string", False
    if kind == "list":
        content = field.get("content_type")
        return (_TYPE_MAP.get(content, "string") if content else "string"), True
    if kind == "dict":
        # proto3 map<string, string> is not "repeated"; represented specially.
        return "map<string, string>", False
    return _scalar_proto_type(field), False


def _message_body(
    name: str,
    fields: dict[str, dict[str, Any]],
    resolve: _Resolver,
    referenced: set[str],
) -> list[str]:
    """Render a single proto3 ``message`` block as a list of lines."""
    lines = [f"message {name} {{"]
    for number, (fname, fspec) in enumerate(sorted(fields.items()), start=1):
        proto_type, repeated = _field_proto_type(fspec, resolve, referenced)
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
    import_path: Callable[[str], str | None] | None = None,
) -> str:
    """Generate proto3 ``.proto`` source text for a single IR element.

    Args:
        element: The IR element dict to emit as the file's main message.
        all_elements: Flat FQN → element index used to look up the fields of
            referenced value objects and entities.
        import_path: Optional lookup from a target FQN to the path of the
            ``.proto`` file that defines it, relative to the ``schemas/`` root.
            When it returns a path, the file imports it and names the type
            ``.<package>.<Name>`` instead of emitting a copy of the message.
            When it returns ``None``, or when no lookup is given, the target is
            emitted as a sibling message in this file.
    """
    flat = all_elements or {}
    own_fqn = element.get("fqn", "")
    name = element.get("name", "") or short_name(own_fqn)
    namespace = module_path(own_fqn) or "protean"

    imports: set[str] = set()

    def resolve(target_fqn: str, referenced: set[str]) -> str:
        ref_name = short_name(target_fqn)
        if not ref_name:
            return "map<string, string>"
        # A self-reference names the message defined in this very file.
        path = (
            import_path(target_fqn)
            if import_path is not None and target_fqn != own_fqn
            else None
        )
        if path is None:
            referenced.add(target_fqn)
            return ref_name
        imports.add(path)
        return f".{module_path(target_fqn) or 'protean'}.{ref_name}"

    referenced: set[str] = set()
    message_blocks: list[list[str]] = [
        _message_body(name, element.get("fields", {}), resolve, referenced)
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
            _message_body(ref_name, target.get("fields", {}), resolve, nested_refs)
        )
        queue.extend(sorted(nested_refs))

    if any(_TIMESTAMP in line for block in message_blocks for line in block):
        imports.add("google/protobuf/timestamp.proto")

    header = ['syntax = "proto3";', f"package {namespace};"]
    header.extend(f'import "{path}";' for path in sorted(imports))

    parts = ["\n".join(header)]
    parts.extend("\n".join(block) for block in message_blocks)
    return "\n\n".join(parts) + "\n"


def generate_proto_schemas(ir: dict[str, Any]) -> dict[str, str]:
    """Generate ``.proto`` text for every data-carrying element in the IR.

    The result maps FQNs to text and carries no file paths, so each text is
    self-contained: referenced value objects and entities are emitted as
    sibling messages, with no imports between files. The schema writer is the
    path that writes importing files.
    """
    flat = _build_flat_elements(ir)
    return {
        fqn: generate_proto_schema(element, all_elements=flat)
        for fqn, element in iter_data_elements(flat)
    }
