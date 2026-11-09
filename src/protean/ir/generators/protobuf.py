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

- Each element's file holds its own proto3 ``message``. When the caller
  passes ``import_path`` (the schema writer does), a file that references a
  value object or entity imports that element's file and names the type by its
  full name, ``.<package>.<Name>``. The leading dot makes ``protoc`` resolve
  the name from the root, so a package such as ``a.a.a`` cannot shadow it.
- With ``import_path``, a target the lookup has no file for is defined as a
  nested message inside the file's main message. Its full name then includes
  the main message's name, so two files in one package never define it twice.
- Without ``import_path``, the referenced value objects and entities become
  sibling messages in the same file, so a single file still compiles on its
  own.
- Optional fields use the proto3 ``optional`` label (explicit presence);
  list / has-many / value-object-list fields use ``repeated``.
- Date/DateTime map to the well-known ``google.protobuf.Timestamp``, written
  ``.google.protobuf.Timestamp`` so a package with a ``google`` part cannot
  shadow it.
- **Field numbers are assigned 1..N in sorted field-name order** (see
  :func:`field_numbers`). Re-generating the same schema always yields the same
  numbers. Adding or removing a field can move the numbers of the fields that
  sort after it. Renaming a field can move its own number and the numbers of
  the fields between its old and new name. Within one ``__version__``,
  ``protean ir diff`` reports a change that moves an event's own field number
  as breaking (``field_number_changed``). It does not check fact events, the
  nested messages of value objects an event holds, or other elements, so their
  numbers can move when their fields change.
- Output is deterministic and sorted.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from protean.ir.generators.base import module_path, short_name
from protean.ir.generators.schema import _build_flat_elements, iter_data_elements

_TIMESTAMP = ".google.protobuf.Timestamp"

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
        # proto3 map<...> is not "repeated"; represented specially.
        target = field.get("target")
        if target:
            return f"map<string, {resolve(target, referenced)}>", False
        return "map<string, string>", False
    return _scalar_proto_type(field), False


def field_numbers(fields: dict[str, dict[str, Any]]) -> dict[str, int]:
    """Return the proto3 field number of each field, keyed by field name.

    Numbers run 1..N in sorted field-name order. The generator writes these
    numbers, and the compatibility check compares them across two snapshots.
    """
    return {name: number for number, name in enumerate(sorted(fields), start=1)}


def _message_body(
    name: str,
    fields: dict[str, dict[str, Any]],
    resolve: _Resolver,
    referenced: set[str],
) -> list[str]:
    """Render a single proto3 ``message`` block as a list of lines."""
    lines = [f"message {name} {{"]
    numbers = field_numbers(fields)
    for fname, fspec in sorted(fields.items()):
        number = numbers[fname]
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


def _local_type_name(
    ref_name: str, namespace: str, main_name: str, *, nested: bool
) -> str:
    """Return how a field names a message defined in the same file.

    ``main_name`` is the file's main message. With ``nested``, the other local
    messages are defined inside it; otherwise they are its siblings in the
    ``namespace`` package.
    """
    # protoc defines a hidden ``<Field>Entry`` message for each map field and
    # looks a bare name up from the innermost message out, so a bare
    # ``LedgerEntry`` can name the hidden message of a ``ledger`` map. The full
    # name always reaches the real one.
    if not ref_name.endswith("Entry"):
        return ref_name
    if nested and ref_name != main_name:
        return f".{namespace}.{main_name}.{ref_name}"
    return f".{namespace}.{ref_name}"


def _map_entry_name(field_name: str) -> str:
    """Return the name ``protoc`` gives the hidden entry message of a map field."""
    words = [word for word in field_name.split("_") if word]
    return "".join(word[0].upper() + word[1:] for word in words) + "Entry"


def _declared_name(
    ref_name: str, main_name: str, entry_names: set[str], taken: set[str]
) -> str:
    """Return the name a referenced message is declared under in this file.

    ``entry_names`` holds the hidden entry message names of the main message's
    map fields, and is empty when referenced messages are siblings of the main
    message. ``taken`` holds the names other messages may be declared under.
    """
    # A message nested inside the main one shares its scope with those hidden
    # entry messages, so a value object named like one of them gets trailing
    # underscores, as many as it takes to clear every other message's name.
    if ref_name == main_name or ref_name not in entry_names:
        return ref_name
    declared = f"{ref_name}_"
    while declared in taken:
        declared += "_"
    return declared


def _referenced_blocks(
    referenced: set[str],
    main_name: str,
    flat: dict[str, dict[str, Any]],
    resolve: _Resolver,
    local_name: Callable[[str], str],
) -> list[list[str]]:
    """Render the messages of referenced value objects and entities.

    Walks the references transitively in a deterministic order, and renders
    each message once.
    """
    ref_blocks: list[list[str]] = []
    seen: set[str] = set()
    queue = sorted(referenced)
    while queue:
        target_fqn = queue.pop(0)
        ref_name = short_name(target_fqn)
        if ref_name in seen or ref_name == main_name:
            continue
        seen.add(ref_name)
        target = flat.get(target_fqn, {})
        nested_refs: set[str] = set()
        ref_blocks.append(
            _message_body(
                local_name(ref_name), target.get("fields", {}), resolve, nested_refs
            )
        )
        queue.extend(sorted(nested_refs))
    return ref_blocks


def _nest_blocks(main_block: list[str], ref_blocks: list[list[str]]) -> list[str]:
    """Return ``main_block`` with ``ref_blocks`` defined inside it."""
    # Nested inside the main message, a target with no file of its own gets a
    # name scoped to this message. As a sibling it would be defined again by
    # every other file in the package that uses it.
    nested = main_block[:-1]
    for block in ref_blocks:
        nested.extend(["", *(f"  {line}" for line in block)])
    nested.append("}")
    return nested


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
            When it returns ``None`` or an empty string, the target is defined
            as a nested message inside this file's main message. When no
            lookup is given, every target is emitted as a sibling message.
    """
    flat = all_elements or {}
    own_fqn = element.get("fqn", "")
    name = element.get("name", "") or short_name(own_fqn)
    namespace = module_path(own_fqn) or "protean"

    nested = import_path is not None
    entry_names = _map_entry_names(element) if nested else set()
    types = _TypeNames(
        own_fqn,
        name,
        namespace,
        entry_names,
        {name, *entry_names, *(short_name(fqn) for fqn in flat)},
        import_path,
    )

    referenced: set[str] = set()
    main_block = _message_body(
        name, element.get("fields", {}), types._resolve, referenced
    )
    ref_blocks = _referenced_blocks(
        referenced, name, flat, types._resolve, types._local_name
    )

    if nested and ref_blocks:
        message_blocks = [_nest_blocks(main_block, ref_blocks)]
    else:
        message_blocks = [main_block, *ref_blocks]

    return _render_proto_file(namespace, types.imports, message_blocks)


def _map_entry_names(element: dict[str, Any]) -> set[str]:
    """The map-entry message names the element's ``dict`` fields declare."""
    return {
        _map_entry_name(fname)
        for fname, fspec in element.get("fields", {}).items()
        if fspec.get("kind") == "dict"
    }


class _TypeNames:
    """Name the proto type of each target one ``.proto`` file references.

    ``imports`` collects the paths of the files the resolved names come from.
    """

    def __init__(
        self,
        own_fqn: str,
        name: str,
        namespace: str,
        entry_names: set[str],
        taken: set[str],
        import_path: Callable[[str], str | None] | None,
    ) -> None:
        self._own_fqn = own_fqn
        self._name = name
        self._namespace = namespace
        self._entry_names = entry_names
        self._taken = taken
        self._import_path = import_path
        self.imports: set[str] = set()

    def _local_name(self, ref_name: str) -> str:
        """The name a target defined in this file is declared under."""
        return _declared_name(ref_name, self._name, self._entry_names, self._taken)

    def _resolve(self, target_fqn: str, referenced: set[str]) -> str:
        """The proto type that names ``target_fqn`` in this file.

        A target defined in this file is added to ``referenced``; a target
        imported from another file adds that file's path to ``imports``.
        """
        ref_name = short_name(target_fqn)
        if not ref_name:
            return "map<string, string>"
        # A self-reference names the message defined in this very file. An
        # element without an fqn can only be matched by its name.
        is_self = (
            target_fqn == self._own_fqn if self._own_fqn else ref_name == self._name
        )
        path = (
            self._import_path(target_fqn) if self._import_path and not is_self else None
        )
        if not path:
            referenced.add(target_fqn)
            return _local_type_name(
                self._local_name(ref_name),
                self._namespace,
                self._name,
                nested=self._import_path is not None,
            )
        self.imports.add(path)
        return f".{module_path(target_fqn) or 'protean'}.{ref_name}"


def _render_proto_file(
    namespace: str, imports: set[str], message_blocks: list[list[str]]
) -> str:
    """Join the header, the imports and the message blocks into file text."""
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
