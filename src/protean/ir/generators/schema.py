"""JSON Schema generator from IR field metadata.

Converts IR element dicts into standard JSON Schema (Draft 2020-12) dicts
with ``x-protean-*`` extension metadata.

Usage::

    from protean.ir.generators.schema import generate_element_schema, generate_schemas

    # Single element
    schema = generate_element_schema(element_ir)

    # All data-carrying elements in the IR
    schemas = generate_schemas(ir)

The output follows JSON Schema Draft 2020-12 conventions:

- ``$schema`` is set to ``https://json-schema.org/draft/2020-12/schema``
- Optional fields use ``anyOf: [{...}, {"type": "null"}]``
- Nested value objects and entities are placed in ``$defs`` with ``$ref``
- Deterministic output: all dict keys are sorted alphabetically
"""

from __future__ import annotations

from typing import Any

from protean.ir.generators.base import short_name

# ---------------------------------------------------------------------------
# IR type → JSON Schema type mapping
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, dict[str, Any]] = {
    "String": {"type": "string"},
    "Text": {"type": "string"},
    "Identifier": {"type": "string"},
    "Integer": {"type": "integer"},
    "Float": {"type": "number"},
    "Boolean": {"type": "boolean"},
    "Date": {"type": "string", "format": "date"},
    "DateTime": {"type": "string", "format": "date-time"},
    "Status": {"type": "string"},
    "Auto": {"type": "string"},
}


# ---------------------------------------------------------------------------
# Field → JSON Schema property conversion
# ---------------------------------------------------------------------------


def _field_to_schema(field: dict[str, Any]) -> dict[str, Any]:
    """Convert a single IR field dict to a JSON Schema property dict.

    This is the core mapping function.  It handles every IR field kind
    (standard, text, identifier, status, auto, list, dict, value_object,
    value_object_list, has_one, has_many, reference) and applies
    constraints (maxLength, minLength, minimum, maximum, enum, etc.).
    """
    kind = field.get("kind", "standard")
    ir_type = field.get("type", "")

    schema: dict[str, Any]

    if kind in ("value_object", "has_one"):
        target = field.get("target", "")
        ref_name = short_name(target)
        schema = {"$ref": f"#/$defs/{ref_name}"}
        return dict(sorted(schema.items()))

    if kind == "has_many":
        target = field.get("target", "")
        ref_name = short_name(target)
        schema = {
            "items": {"$ref": f"#/$defs/{ref_name}"},
            "type": "array",
        }
        return dict(sorted(schema.items()))

    if kind == "value_object_list":
        target = field.get("target", "")
        ref_name = short_name(target)
        schema = {
            "items": {"$ref": f"#/$defs/{ref_name}"},
            "type": "array",
        }
        return dict(sorted(schema.items()))

    if kind == "reference":
        schema = {"type": "string"}
        return schema

    if kind == "list":
        schema: dict[str, Any] = {"type": "array"}
        content_type = field.get("content_type")
        if content_type and content_type in _TYPE_MAP:
            schema["items"] = dict(sorted(_TYPE_MAP[content_type].items()))
        return dict(sorted(schema.items()))

    if kind == "dict":
        return {"type": "object"}

    # standard / text / identifier / status / auto
    base = dict(_TYPE_MAP.get(ir_type, {"type": "string"}))

    # Constraints
    if field.get("max_length") is not None:
        base["maxLength"] = field["max_length"]
    if field.get("min_length") is not None:
        base["minLength"] = field["min_length"]
    if field.get("max_value") is not None:
        base["maximum"] = field["max_value"]
    if field.get("min_value") is not None:
        base["minimum"] = field["min_value"]
    if field.get("choices"):
        base["enum"] = field["choices"]

    return dict(sorted(base.items()))


def _wrap_optional(schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap a schema in ``anyOf`` with ``null`` for optional fields."""
    return {"anyOf": [schema, {"type": "null"}]}


# ---------------------------------------------------------------------------
# Element → JSON Schema conversion
# ---------------------------------------------------------------------------


def _collect_defs(
    fields: dict[str, dict[str, Any]],
    all_elements: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Recursively collect ``$defs`` for referenced value objects and entities.

    Walks the fields looking for ``value_object``, ``value_object_list``,
    ``has_one``, and ``has_many`` kinds, then builds a schema for each
    referenced element and includes it in ``$defs``.
    """
    defs: dict[str, dict[str, Any]] = {}
    ref_kinds = ("value_object", "value_object_list", "has_one", "has_many")

    for field in fields.values():
        kind = field.get("kind")
        if kind not in ref_kinds:
            continue

        target_fqn = field.get("target", "")
        ref_name = short_name(target_fqn)
        if not ref_name or ref_name in defs:
            continue

        # Look up the referenced element in the flat index
        target_element = all_elements.get(target_fqn, {})
        target_fields = target_element.get("fields", {})

        if target_fields:
            nested_props, nested_required = _build_properties(target_fields)
            nested_schema: dict[str, Any] = {
                "properties": dict(sorted(nested_props.items())),
                "type": "object",
            }
            if nested_required:
                nested_schema["required"] = nested_required
            defs[ref_name] = dict(sorted(nested_schema.items()))

            # Recurse into nested refs
            nested_defs = _collect_defs(target_fields, all_elements)
            defs.update(nested_defs)
        else:
            # No fields found — emit a minimal object schema
            defs[ref_name] = {"type": "object"}

    return defs


def _build_properties(
    fields: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Build JSON Schema ``properties`` and ``required`` from IR fields.

    Returns:
        A tuple of (properties dict, sorted required list).
    """
    properties: dict[str, Any] = {}
    required: list[str] = []

    for fname, fspec in sorted(fields.items()):
        prop_schema = _field_to_schema(fspec)

        is_required = fspec.get("required") or fspec.get("identifier")
        if is_required:
            required.append(fname)
        else:
            # Wrap optional fields with anyOf null
            has_ref = "$ref" in prop_schema
            if not has_ref:
                prop_schema = _wrap_optional(prop_schema)

        if fspec.get("description"):
            prop_schema["description"] = fspec["description"]

        if "default" in fspec:
            default_val = fspec["default"]
            if default_val != "<callable>":
                prop_schema["default"] = default_val

        properties[fname] = dict(sorted(prop_schema.items()))

    return properties, sorted(required)


def _build_extension_metadata(
    element: dict[str, Any],
) -> dict[str, Any]:
    """Build ``x-protean-*`` extension metadata from an IR element dict."""
    extensions: dict[str, Any] = {}

    element_type = element.get("element_type", "")
    if element_type:
        extensions["x-protean-element-type"] = element_type.lower()

    fqn = element.get("fqn", "")
    if fqn:
        extensions["x-protean-fqn"] = fqn

    # Aggregate linkage
    part_of = element.get("part_of")
    if part_of:
        extensions["x-protean-aggregate"] = part_of

    # Event-specific metadata
    if element.get("__version__") is not None:
        extensions["x-protean-version"] = element["__version__"]
    if element.get("__type__"):
        extensions["x-protean-type"] = element["__type__"]
    if element.get("published"):
        extensions["x-protean-published"] = True
    if element.get("is_fact_event"):
        extensions["x-protean-is-fact-event"] = True
    if element.get("auto_generated"):
        extensions["x-protean-auto-generated"] = True

    # Aggregate-specific metadata
    if element.get("identity_field"):
        extensions["x-protean-identity-field"] = element["identity_field"]

    options = element.get("options", {})
    if options.get("is_event_sourced"):
        extensions["x-protean-is-event-sourced"] = True

    return dict(sorted(extensions.items()))


# ---------------------------------------------------------------------------
# Flat element index builder
# ---------------------------------------------------------------------------


def _build_flat_elements(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a flat FQN → element dict from the IR for ``$defs`` resolution.

    Scans clusters for aggregates, entities, value objects, commands, and
    events so that ``_collect_defs`` can look up any referenced element.
    """
    elements: dict[str, dict[str, Any]] = {}

    for cluster in ir.get("clusters", {}).values():
        # Aggregate
        agg = cluster.get("aggregate", {})
        agg_fqn = agg.get("fqn", "")
        if agg_fqn:
            elements[agg_fqn] = agg

        # Entities
        for ent_fqn, ent in cluster.get("entities", {}).items():
            elements[ent_fqn] = ent

        # Value objects
        for vo_fqn, vo in cluster.get("value_objects", {}).items():
            elements[vo_fqn] = vo

        # Commands
        for cmd_fqn, cmd in cluster.get("commands", {}).items():
            elements[cmd_fqn] = cmd

        # Events
        for evt_fqn, evt in cluster.get("events", {}).items():
            elements[evt_fqn] = evt

    # Projections (nested under a "projection" key)
    for proj_fqn, proj_wrapper in ir.get("projections", {}).items():
        proj = proj_wrapper.get("projection", proj_wrapper)
        elements[proj_fqn] = proj

    return elements


# ---------------------------------------------------------------------------
# Data-carrying element types
# ---------------------------------------------------------------------------

_DATA_ELEMENT_TYPES = frozenset(
    {"AGGREGATE", "ENTITY", "VALUE_OBJECT", "COMMAND", "EVENT", "PROJECTION"}
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_element_schema(
    element: dict[str, Any],
    *,
    all_elements: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Generate a JSON Schema dict for a single IR element.

    Args:
        element: An IR element dict (aggregate, entity, value object,
            command, event, or projection) containing at minimum a
            ``fields`` key.
        all_elements: Optional flat FQN → element index used to resolve
            ``$defs`` for nested value objects and entities.  When
            ``None``, ``$defs`` for referenced elements will use a
            minimal ``{"type": "object"}`` placeholder.

    Returns:
        A JSON Schema Draft 2020-12 dict with ``x-protean-*`` extensions.
    """
    fields = element.get("fields", {})
    properties, required = _build_properties(fields)

    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "properties": dict(sorted(properties.items())),
        "type": "object",
    }

    if required:
        schema["required"] = required

    # Title from element name
    name = element.get("name", "")
    if name:
        schema["title"] = name

    # Description from element description
    description = element.get("description")
    if description:
        schema["description"] = description

    # $defs for nested references
    flat = all_elements or {}
    defs = _collect_defs(fields, flat)
    if defs:
        schema["$defs"] = dict(sorted(defs.items()))

    # x-protean-* extensions
    extensions = _build_extension_metadata(element)
    schema.update(extensions)

    return dict(sorted(schema.items()))


def generate_schemas(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Generate JSON Schema dicts for all data-carrying elements in the IR.

    Walks every cluster in the IR and generates a schema for each aggregate,
    entity, value object, command, and event.  Also processes projections.

    Args:
        ir: The full IR dict (from ``IRBuilder.build()``).

    Returns:
        A dict mapping FQN → JSON Schema dict, sorted by FQN.
    """
    flat = _build_flat_elements(ir)
    schemas: dict[str, dict[str, Any]] = {}

    for fqn, element in sorted(flat.items()):
        element_type = element.get("element_type", "").upper()
        if element_type not in _DATA_ELEMENT_TYPES:
            continue

        # Only generate for elements that have fields
        if "fields" not in element:
            continue

        schemas[fqn] = generate_element_schema(element, all_elements=flat)

    return dict(sorted(schemas.items()))
