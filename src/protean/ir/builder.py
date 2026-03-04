"""IRBuilder — walks a Domain composite root and produces an IR dict.

Usage::

    from protean.ir.builder import IRBuilder

    domain.init()
    ir = IRBuilder(domain).build()
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from protean.ir import SCHEMA_VERSION

if TYPE_CHECKING:
    from protean.domain import Domain


class IRBuilder:
    """Build the Intermediate Representation for a Protean domain.

    The domain **must** be initialised (``domain.init()``) before calling
    :meth:`build` — the builder reads the fully-wired composite root.
    """

    def __init__(self, domain: Domain) -> None:
        self._domain = domain
        self._diagnostics: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        """Return the complete IR dictionary."""
        ir: dict[str, Any] = {
            "$schema": f"https://protean.dev/ir/v{SCHEMA_VERSION}/schema.json",
            "checksum": "",
            "clusters": {},
            "contracts": {"events": []},
            "diagnostics": [],
            "domain": self._build_domain_metadata(),
            "elements": {},
            "flows": {
                "domain_services": {},
                "process_managers": {},
                "subscribers": {},
            },
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ir_version": SCHEMA_VERSION,
            "projections": {},
        }

        # Attach collected diagnostics
        ir["diagnostics"] = sorted(self._diagnostics, key=lambda d: d.get("code", ""))
        # Compute checksum last
        ir["checksum"] = self._compute_checksum(ir)
        return ir

    # ------------------------------------------------------------------
    # Domain metadata
    # ------------------------------------------------------------------

    def _build_domain_metadata(self) -> dict[str, Any]:
        cfg = self._domain.config
        return {
            "camel_case_name": self._domain.camel_case_name,
            "command_processing": cfg["command_processing"],
            "event_processing": cfg["event_processing"],
            "identity_strategy": cfg["identity_strategy"],
            "identity_type": cfg["identity_type"],
            "name": self._domain.name,
            "normalized_name": self._domain.normalized_name,
        }

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------

    def _extract_fields(self, cls: type) -> dict[str, Any]:
        """Extract field definitions from a domain element class.

        Returns a dict keyed by field name, each value a sparse IR field dict.
        """

        from protean.fields.association import HasMany, HasOne, Reference
        from protean.fields.basic import ValueObjectList
        from protean.fields.embedded import ValueObject
        from protean.fields.resolved import ResolvedField
        from protean.utils import fqn
        from protean.utils.reflection import declared_fields

        result: dict[str, Any] = {}
        field_meta: dict[str, Any] = getattr(cls, "__protean_field_meta__", {})

        for name, field_obj in sorted(declared_fields(cls).items()):
            entry: dict[str, Any] = {}

            if isinstance(field_obj, ValueObject):
                entry["kind"] = "value_object"
                entry["target"] = fqn(field_obj.value_object_cls)
                if field_obj.required:
                    entry["required"] = True

            elif isinstance(field_obj, ValueObjectList):
                entry["kind"] = "value_object_list"
                if isinstance(field_obj.content_type, ValueObject):
                    entry["target"] = fqn(field_obj.content_type.value_object_cls)
                else:
                    entry["target"] = fqn(field_obj.content_type)

            elif isinstance(field_obj, HasOne):
                entry["kind"] = "has_one"
                entry["target"] = fqn(field_obj.to_cls)

            elif isinstance(field_obj, HasMany):
                entry["kind"] = "has_many"
                entry["target"] = fqn(field_obj.to_cls)

            elif isinstance(field_obj, Reference):
                entry["kind"] = "reference"
                entry["target"] = fqn(field_obj.to_cls)
                entry["linked_attribute"] = field_obj.linked_attribute
                if field_obj._auto_generated:
                    entry["auto_generated"] = True

            elif isinstance(field_obj, ResolvedField):
                entry = self._extract_resolved_field(field_obj, field_meta.get(name))

            else:
                # Unknown field type — skip
                continue

            result[name] = dict(sorted(entry.items()))

        return result

    def _extract_resolved_field(self, field: Any, spec: Any | None) -> dict[str, Any]:
        """Build an IR field dict from a ResolvedField + optional FieldSpec."""
        entry: dict[str, Any] = {}
        python_type = field._python_type
        base_type = self._unwrap_type(python_type)

        # Auto-generated identifier fields (injected by __init_subclass__)
        # have field_kind="standard" but should be kind="auto"
        if field._auto_generated and field.identifier:
            entry["kind"] = "auto"
            entry["type"] = "Auto"
        elif self._is_list_type(base_type):
            entry["kind"] = "list"
            entry["type"] = "List"
            ct = field.content_type
            if ct is not None:
                entry["content_type"] = self._python_type_name(ct)
        elif self._is_dict_type(base_type, python_type):
            entry["kind"] = "dict"
            entry["type"] = "Dict"
        else:
            kind = field.field_kind
            entry["kind"] = kind
            entry["type"] = self._resolve_type_name(base_type, kind)

        # Sparse optional attributes
        if field.required:
            entry["required"] = True
        if field.identifier:
            entry["identifier"] = True
        if field.unique and not field.identifier:
            # identifier already implies unique; don't duplicate
            entry["unique"] = True
        if field._auto_generated:
            entry["auto_generated"] = True
        if field.max_length is not None:
            entry["max_length"] = field.max_length
        if field.min_value is not None:
            entry["min_value"] = field.min_value
        if field.max_value is not None:
            entry["max_value"] = field.max_value
        if field.sanitize:
            entry["sanitize"] = True
        if field.increment:
            entry["increment"] = True
        if getattr(field, "description", None):
            entry["description"] = field.description

        # Choices — from the original FieldSpec
        if spec is not None and getattr(spec, "choices", None) is not None:
            from enum import Enum

            choices = spec.choices
            if isinstance(choices, type) and issubclass(choices, Enum):
                choices_list = sorted(item.value for item in choices)
            else:
                choices_list = sorted(str(c) for c in choices)
            entry["choices"] = choices_list

        # Default — from FieldSpec for accurate representation
        if spec is not None:
            from protean.fields.spec import _UNSET

            if spec.default is not _UNSET:
                if callable(spec.default):
                    entry["default"] = "<callable>"
                else:
                    entry["default"] = spec.default
        elif field.default is not None:
            # Fallback to ResolvedField default if no spec
            if callable(field.default):
                entry["default"] = "<callable>"
            else:
                entry["default"] = field.default

        return entry

    @staticmethod
    def _unwrap_type(python_type: type | None) -> type | None:
        """Unwrap Optional/Union to get the base concrete type.

        Examples:
            ``float | None``  → ``float``
            ``str | int | UUID``  → ``str``  (first non-None arg)
            ``list[str]``  → ``list[str]``  (unchanged)
            ``Literal['A','B'] | None``  → ``str``  (first Literal arg type)
        """
        import types as _types
        import typing

        if python_type is None:
            return None

        origin = typing.get_origin(python_type)

        # Handle Union types (e.g., float | None, str | int | UUID)
        if origin is _types.UnionType or origin is typing.Union:
            args = [a for a in typing.get_args(python_type) if a is not type(None)]
            if args:
                # Recurse on first non-None type to handle nested generics
                return IRBuilder._unwrap_type(args[0])
            return None

        # Handle Literal types — extract the Python type of the first value
        if origin is typing.Literal:
            literal_args = typing.get_args(python_type)
            if literal_args:
                return type(literal_args[0])
            return str

        return python_type

    @staticmethod
    def _is_list_type(python_type: type | None) -> bool:
        """Check if a (possibly unwrapped) type is a list origin."""
        import typing

        if python_type is None:
            return False
        return typing.get_origin(python_type) is list

    @staticmethod
    def _is_dict_type(base_type: type | None, original_type: type | None) -> bool:
        """Check if a type is a dict.

        Handles both ``dict`` and ``dict | list`` (from Dict() field).
        """
        import types as _types
        import typing

        if base_type is dict:
            return True
        # Dict() field creates `dict | list` annotation
        origin = typing.get_origin(original_type)
        if origin is _types.UnionType or origin is typing.Union:
            args = [a for a in typing.get_args(original_type) if a is not type(None)]
            if dict in args:
                return True
        return False

    @staticmethod
    def _resolve_type_name(python_type: type | None, kind: str) -> str:
        """Map a Python type + field kind to the IR type name."""
        import datetime as _dt

        _TYPE_MAP: dict[tuple[type, str], str] = {
            (str, "standard"): "String",
            (str, "text"): "Text",
            (str, "identifier"): "Identifier",
            (str, "auto"): "Auto",
            (int, "standard"): "Integer",
            (int, "auto"): "Auto",
            (float, "standard"): "Float",
            (bool, "standard"): "Boolean",
            (_dt.date, "standard"): "Date",
            (_dt.datetime, "standard"): "DateTime",
        }
        if python_type is not None:
            result = _TYPE_MAP.get((python_type, kind))
            if result:
                return result
        return "String"  # Fallback

    @staticmethod
    def _python_type_name(python_type: type | None) -> str:
        """Map a Python type to its IR content_type name."""
        import datetime as _dt

        _CONTENT_TYPE_MAP: dict[type, str] = {
            str: "String",
            int: "Integer",
            float: "Float",
            bool: "Boolean",
            dict: "dict",
            _dt.date: "Date",
            _dt.datetime: "DateTime",
        }
        if python_type is not None:
            return _CONTENT_TYPE_MAP.get(python_type, python_type.__name__)
        return "String"

    # ------------------------------------------------------------------
    # Checksum
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_checksum(ir: dict[str, Any]) -> str:
        """SHA-256 of canonical JSON with volatile keys removed."""
        ir_copy = {k: v for k, v in ir.items() if k not in ("generated_at", "checksum")}
        canonical = json.dumps(ir_copy, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"
