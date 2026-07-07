"""Avro schema generator from IR field metadata.

Converts IR element dicts into Apache Avro schema dicts (`.avsc` content).

Usage::

    from protean.ir.generators.avro import generate_avro_schema, generate_avro_schemas

    # Single element
    schema = generate_avro_schema(element_ir, all_elements=flat_index)

    # All data-carrying elements in the IR
    schemas = generate_avro_schemas(ir)

Conventions:

- Each element becomes an Avro ``record`` with a ``namespace`` from its module.
- Optional fields become a ``["null", <type>]`` union with ``"default": null``
  (null first, per the Avro rule that a union default matches the first branch).
- Date/DateTime/Identifier map to Avro logical types (``date``,
  ``timestamp-millis``, ``uuid``).
- Nested value objects / entities become named records, defined once and
  referenced by fullname (``namespace.Name``) on subsequent use, so a value
  object reused across namespaces stays resolvable (Avro's named-type model).
- Output is deterministic: fields are emitted in sorted order.
"""

from __future__ import annotations

from typing import Any

from protean.ir.generators.base import module_path, short_name
from protean.ir.generators.schema import _build_flat_elements, iter_data_elements

# ---------------------------------------------------------------------------
# IR type → Avro type mapping
# ---------------------------------------------------------------------------
#
# Integers map to ``long`` (64-bit) because Python ints are unbounded and a
# 32-bit ``int`` would silently truncate. Floats map to ``double`` for the same
# reason. Logical types annotate a base type with domain meaning.

_TYPE_MAP: dict[str, Any] = {
    "String": "string",
    "Text": "string",
    "Status": "string",
    "Identifier": {"type": "string", "logicalType": "uuid"},
    "Integer": "long",
    "Float": "double",
    "Boolean": "boolean",
    "Date": {"type": "int", "logicalType": "date"},
    "DateTime": {"type": "long", "logicalType": "timestamp-millis"},
    "Auto": "string",
}


def _avro_namespace(element: dict[str, Any]) -> str:
    """Derive an Avro namespace (the element's module) for an element."""
    return module_path(element.get("fqn", "")) or "protean"


def _scalar_avro_type(field: dict[str, Any]) -> Any:
    """Map a scalar/auto IR field to its Avro type (no optional wrapping)."""
    ir_type = field.get("type", "")
    if field.get("kind") == "auto" or ir_type == "Auto":
        return "long" if field.get("increment") else "string"
    return _TYPE_MAP.get(ir_type, "string")


def _field_to_avro_type(
    field: dict[str, Any],
    all_elements: dict[str, dict[str, Any]],
    defined: set[str],
) -> Any:
    """Return the Avro type for an IR field (before optional wrapping).

    ``defined`` tracks record names already emitted in this schema so a
    repeated value-object/entity reference is emitted by name, not redefined
    (Avro rejects a duplicate record definition).
    """
    kind = field.get("kind", "standard")

    if kind in ("value_object", "has_one"):
        return _named_record(field.get("target", ""), all_elements, defined)

    if kind in ("value_object_list", "has_many"):
        return {
            "type": "array",
            "items": _named_record(field.get("target", ""), all_elements, defined),
        }

    if kind == "reference":
        return "string"

    if kind == "list":
        content_type = field.get("content_type")
        items = _TYPE_MAP.get(content_type, "string") if content_type else "string"
        return {"type": "array", "items": items}

    if kind == "dict":
        return {"type": "map", "values": "string"}

    return _scalar_avro_type(field)


def _named_record(
    target_fqn: str,
    all_elements: dict[str, dict[str, Any]],
    defined: set[str],
) -> Any:
    """Build (or reference by fullname) the Avro record for a nested element.

    ``defined`` tracks records by their Avro *fullname* (``namespace.Name``),
    and a repeated reference is emitted as that fullname string. Referencing by
    the bare short name would be wrong when the nested record's namespace
    differs from the enclosing record's: Avro resolves an unqualified name
    against the enclosing namespace, so a shared-kernel value object reused
    across clusters would resolve to a non-existent type.
    """
    ref_name = short_name(target_fqn)
    if not ref_name:
        return {"type": "map", "values": "string"}

    target = all_elements.get(target_fqn, {})
    namespace = _avro_namespace(target)
    fullname = f"{namespace}.{ref_name}"
    if fullname in defined:
        # Already defined earlier in this schema — reference by fullname.
        return fullname
    defined.add(fullname)

    return {
        "type": "record",
        "name": ref_name,
        "namespace": namespace,
        "fields": _build_avro_fields(target.get("fields", {}), all_elements, defined),
    }


def _build_avro_fields(
    fields: dict[str, dict[str, Any]],
    all_elements: dict[str, dict[str, Any]],
    defined: set[str],
) -> list[dict[str, Any]]:
    """Build the Avro ``fields`` list from IR fields (deterministic order)."""
    result: list[dict[str, Any]] = []
    for fname, fspec in sorted(fields.items()):
        avro_type = _field_to_avro_type(fspec, all_elements, defined)
        entry: dict[str, Any] = {"name": fname}

        is_required = fspec.get("required") or fspec.get("identifier")
        has_default = "default" in fspec and fspec["default"] != "<callable>"

        if is_required:
            entry["type"] = avro_type
            if has_default:
                entry["default"] = fspec["default"]
        else:
            # Optional: null-first union. Avro requires a union default to match
            # the first branch, so the default is always null — a non-null IR
            # default cannot be expressed on a null-first union.
            entry["type"] = ["null", avro_type]
            entry["default"] = None

        if fspec.get("description"):
            entry["doc"] = fspec["description"]

        # A declared field rename (renamed_from) becomes Avro field aliases so a
        # reader on the new schema resolves data written under the old name —
        # keeping the rename backward-compatible on the wire, not just at
        # Protean's read-time alias resolution.
        renamed_from = fspec.get("renamed_from")
        if renamed_from:
            entry["aliases"] = list(renamed_from)

        result.append(entry)
    return result


def generate_avro_schema(
    element: dict[str, Any],
    *,
    all_elements: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate an Avro record schema dict for a single IR element."""
    flat = all_elements or {}
    name = element.get("name", "") or short_name(element.get("fqn", ""))
    namespace = _avro_namespace(element)
    # Seed ``defined`` with this record's fullname so a self-reference (a field
    # whose value object points back to it) is emitted by name, not redefined.
    defined: set[str] = {f"{namespace}.{name}"}

    schema: dict[str, Any] = {
        "type": "record",
        "name": name,
        "namespace": namespace,
        "fields": _build_avro_fields(element.get("fields", {}), flat, defined),
    }
    if element.get("description"):
        schema["doc"] = element["description"]
    return schema


def generate_avro_schemas(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Generate Avro schema dicts for every data-carrying element in the IR."""
    flat = _build_flat_elements(ir)
    return {
        fqn: generate_avro_schema(element, all_elements=flat)
        for fqn, element in iter_data_elements(flat)
    }
