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
            "clusters": self._build_clusters(),
            "contracts": self._build_contracts(),
            "diagnostics": [],
            "domain": self._build_domain_metadata(),
            "elements": self._build_elements_index(),
            "flows": self._build_flows(),
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ir_version": SCHEMA_VERSION,
            "projections": self._build_projections(),
        }

        # Collect diagnostics (must run after clusters are built)
        self._collect_diagnostics(ir)

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
    # Deprecation extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_deprecated(cls: type) -> dict[str, str] | None:
        """Return the normalized ``deprecated`` metadata from an element's meta_.

        Returns ``None`` when the element is not deprecated (sparse IR).
        """
        return getattr(getattr(cls, "meta_", None), "deprecated", None)

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
                if field_obj.via is not None:
                    entry["via"] = field_obj.via

            elif isinstance(field_obj, HasMany):
                entry["kind"] = "has_many"
                entry["target"] = fqn(field_obj.to_cls)
                if field_obj.via is not None:
                    entry["via"] = field_obj.via

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

            # Deprecated — for non-ResolvedField types (ResolvedField handles
            # this in _extract_resolved_field via the FieldSpec).
            if not isinstance(field_obj, ResolvedField):
                deprecated = getattr(field_obj, "deprecated", None)
                if deprecated is not None:
                    entry["deprecated"] = deprecated

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
        if field.min_length is not None:
            entry["min_length"] = field.min_length
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

        # Transitions — from ResolvedField
        if getattr(field, "transitions", None) is not None:
            entry["transitions"] = field.transitions

        # Deprecated — from FieldSpec
        if spec is not None and getattr(spec, "deprecated", None) is not None:
            entry["deprecated"] = spec.deprecated

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
            (str, "status"): "Status",
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
    # Element extractors
    # ------------------------------------------------------------------

    def _extract_invariants(self, cls: type) -> dict[str, list[str]]:
        """Extract pre/post invariant method names as sorted lists."""
        invariants = getattr(cls, "_invariants", {})
        return {
            "post": sorted(invariants.get("post", {}).keys()),
            "pre": sorted(invariants.get("pre", {}).keys()),
        }

    def _extract_aggregate(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract aggregate IR dict."""
        from protean.utils import fqn
        from protean.utils.reflection import _ID_FIELD_NAME

        entry: dict[str, Any] = {}

        # Sparse: only emit deprecated when set
        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        # Apply handlers (ES aggregates only)
        if cls.meta_.is_event_sourced:
            projections = getattr(cls, "_projections", {})
            if projections:
                apply_handlers: dict[str, str] = {}
                for event_fqn, methods in sorted(projections.items()):
                    for method in methods:
                        apply_handlers[event_fqn] = method.__name__
                entry["apply_handlers"] = dict(sorted(apply_handlers.items()))

        # Description from docstring
        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "AGGREGATE"
        entry["fields"] = self._extract_fields(cls)
        entry["fqn"] = fqn(cls)
        entry["identity_field"] = getattr(cls, _ID_FIELD_NAME, "id")
        entry["invariants"] = self._extract_invariants(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        entry["options"] = dict(
            sorted(
                {
                    "auto_add_id_field": cls.meta_.auto_add_id_field,
                    "fact_events": cls.meta_.fact_events,
                    "is_event_sourced": cls.meta_.is_event_sourced,
                    "limit": cls.meta_.limit,
                    "provider": cls.meta_.provider,
                    "schema_name": cls.meta_.schema_name,
                    "stream_category": cls.meta_.stream_category,
                }.items()
            )
        )

        return dict(sorted(entry.items()))

    def _extract_entity(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract entity IR dict."""
        from protean.utils import fqn
        from protean.utils.reflection import _ID_FIELD_NAME

        entry: dict[str, Any] = {}

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "ENTITY"
        entry["fields"] = self._extract_fields(cls)
        entry["fqn"] = fqn(cls)
        entry["identity_field"] = getattr(cls, _ID_FIELD_NAME, "id")
        entry["invariants"] = self._extract_invariants(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        entry["options"] = dict(
            sorted(
                {
                    "auto_add_id_field": cls.meta_.auto_add_id_field,
                    "limit": cls.meta_.limit,
                    "provider": cls.meta_.provider,
                    "schema_name": cls.meta_.schema_name,
                }.items()
            )
        )

        agg_cls = getattr(cls.meta_, "aggregate_cluster", None)
        if agg_cls is not None:
            entry["part_of"] = fqn(agg_cls)

        return dict(sorted(entry.items()))

    def _extract_value_object(
        self, cls: type, record: Any, aggregate_fqn: str | None = None
    ) -> dict[str, Any]:
        """Extract value object IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "VALUE_OBJECT"
        entry["fields"] = self._extract_fields(cls)
        entry["fqn"] = fqn(cls)
        entry["invariants"] = self._extract_invariants(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        if aggregate_fqn is not None:
            entry["part_of"] = aggregate_fqn

        return dict(sorted(entry.items()))

    def _extract_command(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract command IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}
        entry["__type__"] = getattr(cls, "__type__", "")
        entry["__version__"] = getattr(cls, "__version__", 1)

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "COMMAND"
        entry["fields"] = self._extract_fields(cls)
        entry["fqn"] = fqn(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        agg_cls = self._resolve_aggregate_cls(cls)
        if agg_cls is not None:
            entry["part_of"] = fqn(agg_cls)

        return dict(sorted(entry.items()))

    def _extract_event(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract event IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}
        entry["__type__"] = getattr(cls, "__type__", "")
        entry["__version__"] = getattr(cls, "__version__", 1)

        if record.auto_generated:
            entry["auto_generated"] = True

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "EVENT"
        entry["fields"] = self._extract_fields(cls)
        entry["fqn"] = fqn(cls)
        entry["is_fact_event"] = getattr(cls.meta_, "is_fact_event", False)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        agg_cls = self._resolve_aggregate_cls(cls)
        if agg_cls is not None:
            entry["part_of"] = fqn(agg_cls)

        # Sparse: only emit published when true
        if getattr(cls.meta_, "published", False):
            entry["published"] = True

        return dict(sorted(entry.items()))

    def _extract_handler_map(self, cls: type) -> dict[str, list[str]]:
        """Extract handler map as {__type__: sorted([method_names])}."""
        handlers = getattr(cls, "_handlers", {})
        result: dict[str, list[str]] = {}
        for type_key, methods in sorted(handlers.items()):
            if methods:
                result[type_key] = sorted(m.__name__ for m in methods)
        return result

    def _extract_subscription(self, cls: type) -> dict[str, Any]:
        """Extract subscription config as {type, profile, config}."""
        sub_type = getattr(cls.meta_, "subscription_type", None)
        sub_profile = getattr(cls.meta_, "subscription_profile", None)
        sub_config = getattr(cls.meta_, "subscription_config", {})
        return {
            "config": sub_config if sub_config else {},
            "profile": sub_profile.value if sub_profile else None,
            "type": sub_type.value if sub_type else None,
        }

    def _extract_command_handler(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract command handler IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "COMMAND_HANDLER"
        entry["fqn"] = fqn(cls)
        entry["handlers"] = self._extract_handler_map(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        agg_cls = self._resolve_aggregate_cls(cls)
        if agg_cls is not None:
            entry["part_of"] = fqn(agg_cls)

        entry["stream_category"] = getattr(cls.meta_, "stream_category", None)
        entry["subscription"] = self._extract_subscription(cls)

        return dict(sorted(entry.items()))

    def _extract_event_handler(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract event handler IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "EVENT_HANDLER"
        entry["fqn"] = fqn(cls)
        entry["handlers"] = self._extract_handler_map(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        agg_cls = self._resolve_aggregate_cls(cls)
        if agg_cls is not None:
            entry["part_of"] = fqn(agg_cls)

        entry["source_stream"] = getattr(cls.meta_, "source_stream", None)
        entry["stream_category"] = getattr(cls.meta_, "stream_category", None)
        entry["subscription"] = self._extract_subscription(cls)

        return dict(sorted(entry.items()))

    def _extract_application_service(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract application service IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "APPLICATION_SERVICE"
        entry["fqn"] = fqn(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        agg_cls = self._resolve_aggregate_cls(cls)
        if agg_cls is not None:
            entry["part_of"] = fqn(agg_cls)

        return dict(sorted(entry.items()))

    def _extract_repository(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract repository IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        # Sparse: omit database when default "ALL"
        database = getattr(cls.meta_, "database", "ALL")
        if database != "ALL":
            entry["database"] = database

        entry["element_type"] = "REPOSITORY"
        entry["fqn"] = fqn(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        agg_cls = self._resolve_aggregate_cls(cls)
        if agg_cls is not None:
            entry["part_of"] = fqn(agg_cls)

        return dict(sorted(entry.items()))

    def _extract_database_model(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract database model IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}

        database = getattr(cls.meta_, "database", None)
        if database is not None:
            entry["database"] = database

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "DATABASE_MODEL"
        entry["fqn"] = fqn(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        agg_cls = self._resolve_aggregate_cls(cls)
        if agg_cls is not None:
            entry["part_of"] = fqn(agg_cls)

        schema_name = getattr(cls.meta_, "schema_name", None)
        if schema_name is not None:
            entry["schema_name"] = schema_name

        return dict(sorted(entry.items()))

    # ------------------------------------------------------------------
    # Projection extractors
    # ------------------------------------------------------------------

    def _extract_projection(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract projection IR dict."""
        from protean.utils import fqn
        from protean.utils.reflection import _ID_FIELD_NAME

        entry: dict[str, Any] = {}

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "PROJECTION"
        entry["fields"] = self._extract_fields(cls)
        entry["fqn"] = fqn(cls)
        entry["identity_field"] = getattr(cls, _ID_FIELD_NAME, None)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        order_by = getattr(cls.meta_, "order_by", ())
        entry["options"] = dict(
            sorted(
                {
                    "cache": getattr(cls.meta_, "cache", None),
                    "limit": getattr(cls.meta_, "limit", 100),
                    "order_by": list(order_by) if order_by else [],
                    "provider": getattr(cls.meta_, "provider", "default"),
                    "schema_name": getattr(cls.meta_, "schema_name", None),
                }.items()
            )
        )

        return dict(sorted(entry.items()))

    def _extract_projector(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract projector IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}

        aggregates = getattr(cls.meta_, "aggregates", [])
        entry["aggregates"] = sorted(fqn(a) for a in aggregates) if aggregates else []

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "PROJECTOR"
        entry["fqn"] = fqn(cls)
        entry["handlers"] = self._extract_handler_map(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        projector_for = getattr(cls.meta_, "projector_for", None)
        if projector_for is not None:
            entry["projector_for"] = fqn(projector_for)

        entry["stream_categories"] = sorted(getattr(cls.meta_, "stream_categories", []))
        entry["subscription"] = self._extract_subscription(cls)

        return dict(sorted(entry.items()))

    def _extract_query(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract query IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}
        entry["__type__"] = getattr(cls, "__type__", "")

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "QUERY"
        entry["fields"] = self._extract_fields(cls)
        entry["fqn"] = fqn(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        part_of = getattr(cls.meta_, "part_of", None)
        if part_of is not None:
            entry["part_of"] = fqn(part_of)

        return dict(sorted(entry.items()))

    def _extract_query_handler(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract query handler IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "QUERY_HANDLER"
        entry["fqn"] = fqn(cls)
        entry["handlers"] = self._extract_handler_map(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        part_of = getattr(cls.meta_, "part_of", None)
        if part_of is not None:
            entry["part_of"] = fqn(part_of)

        return dict(sorted(entry.items()))

    def _build_projections(self) -> dict[str, Any]:
        """Build projections dict keyed by projection FQN."""
        from protean.utils import fqn

        registry = self._domain._domain_registry
        projections: dict[str, Any] = {}

        # Build projection entries
        for record in registry._elements.get("PROJECTION", {}).values():
            proj_cls = record.cls
            proj_fqn = fqn(proj_cls)
            projections[proj_fqn] = {
                "projection": self._extract_projection(proj_cls, record),
                "projectors": {},
                "queries": {},
                "query_handlers": {},
            }

        # Populate projectors
        for record in registry._elements.get("PROJECTOR", {}).values():
            cls = record.cls
            proj_for = getattr(cls.meta_, "projector_for", None)
            if proj_for is not None:
                proj_fqn = fqn(proj_for)
                if proj_fqn in projections:
                    projections[proj_fqn]["projectors"][fqn(cls)] = (
                        self._extract_projector(cls, record)
                    )

        # Populate queries
        for record in registry._elements.get("QUERY", {}).values():
            cls = record.cls
            part_of = getattr(cls.meta_, "part_of", None)
            if part_of is not None:
                proj_fqn = fqn(part_of)
                if proj_fqn in projections:
                    projections[proj_fqn]["queries"][fqn(cls)] = self._extract_query(
                        cls, record
                    )

        # Populate query handlers
        for record in registry._elements.get("QUERY_HANDLER", {}).values():
            cls = record.cls
            part_of = getattr(cls.meta_, "part_of", None)
            if part_of is not None:
                proj_fqn = fqn(part_of)
                if proj_fqn in projections:
                    projections[proj_fqn]["query_handlers"][fqn(cls)] = (
                        self._extract_query_handler(cls, record)
                    )

        # Sort inner dicts
        for proj in projections.values():
            for section in ("projectors", "queries", "query_handlers"):
                proj[section] = dict(sorted(proj[section].items()))

        return dict(sorted(projections.items()))

    # ------------------------------------------------------------------
    # Flow extractors
    # ------------------------------------------------------------------

    def _extract_domain_service(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract domain service IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "DOMAIN_SERVICE"
        entry["fqn"] = fqn(cls)
        entry["invariants"] = self._extract_invariants(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        part_of = getattr(cls.meta_, "part_of", None)
        if part_of is not None:
            if isinstance(part_of, (list, tuple)):
                entry["part_of"] = sorted(fqn(a) for a in part_of)
            else:
                entry["part_of"] = [fqn(part_of)]

        return dict(sorted(entry.items()))

    def _extract_process_manager(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract process manager IR dict."""
        from protean.utils import fqn
        from protean.utils.reflection import _ID_FIELD_NAME

        entry: dict[str, Any] = {}

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "PROCESS_MANAGER"
        entry["fields"] = self._extract_fields(cls)
        entry["fqn"] = fqn(cls)

        # PM handler format: {__type__: {methods, start, end, correlate}}
        handlers = getattr(cls, "_handlers", {})
        pm_handlers: dict[str, Any] = {}
        for type_key, methods in sorted(handlers.items()):
            if methods:
                method_entry: dict[str, Any] = {}
                first_method = next(iter(methods))
                correlate = getattr(first_method, "_correlate", None)
                if isinstance(correlate, dict):
                    method_entry["correlate"] = correlate
                elif correlate:
                    method_entry["correlate"] = str(correlate)
                method_entry["end"] = getattr(first_method, "_end", False)
                method_entry["methods"] = sorted(m.__name__ for m in methods)
                method_entry["start"] = getattr(first_method, "_start", False)
                pm_handlers[type_key] = method_entry
        entry["handlers"] = pm_handlers

        entry["identity_field"] = getattr(cls, _ID_FIELD_NAME, "id")
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        entry["stream_categories"] = sorted(getattr(cls.meta_, "stream_categories", []))
        entry["stream_category"] = getattr(cls.meta_, "stream_category", None)
        entry["subscription"] = self._extract_subscription(cls)

        # Transition event
        transition_cls = getattr(cls, "_transition_event_cls", None)
        if transition_cls is not None:
            entry["transition_event"] = {
                "__type__": getattr(transition_cls, "__type__", ""),
                "fqn": fqn(transition_cls),
            }

        return dict(sorted(entry.items()))

    def _extract_subscriber(self, cls: type, record: Any) -> dict[str, Any]:
        """Extract subscriber IR dict."""
        from protean.utils import fqn

        entry: dict[str, Any] = {}
        entry["broker"] = getattr(cls.meta_, "broker", "default")

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        doc = (cls.__doc__ or "").strip()
        if doc:
            entry["description"] = doc

        entry["element_type"] = "SUBSCRIBER"
        entry["fqn"] = fqn(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__
        entry["stream"] = getattr(cls.meta_, "stream", None)

        return dict(sorted(entry.items()))

    def _build_flows(self) -> dict[str, Any]:
        """Build flows dict with domain_services, process_managers, subscribers."""
        from protean.utils import fqn

        registry = self._domain._domain_registry
        flows: dict[str, Any] = {
            "domain_services": {},
            "process_managers": {},
            "subscribers": {},
        }

        for record in registry._elements.get("DOMAIN_SERVICE", {}).values():
            cls = record.cls
            flows["domain_services"][fqn(cls)] = self._extract_domain_service(
                cls, record
            )

        for record in registry._elements.get("PROCESS_MANAGER", {}).values():
            cls = record.cls
            flows["process_managers"][fqn(cls)] = self._extract_process_manager(
                cls, record
            )

        for record in registry._elements.get("SUBSCRIBER", {}).values():
            cls = record.cls
            flows["subscribers"][fqn(cls)] = self._extract_subscriber(cls, record)

        # Sort each section
        for section in flows:
            flows[section] = dict(sorted(flows[section].items()))

        return flows

    # ------------------------------------------------------------------
    # Cluster assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_aggregate_cls(cls: type) -> type | None:
        """Resolve the root aggregate class for an element.

        Tries ``aggregate_cluster`` first (set by resolver for entities,
        commands, events), then falls back to traversing ``part_of``
        (needed for fact events generated after cluster assignment).
        """
        from protean.core.aggregate import BaseAggregate

        agg = getattr(cls.meta_, "aggregate_cluster", None)
        if agg is not None:
            return agg

        part_of = getattr(cls.meta_, "part_of", None)
        while part_of is not None:
            if isinstance(part_of, type) and issubclass(part_of, BaseAggregate):
                return part_of
            part_of = getattr(getattr(part_of, "meta_", None), "part_of", None)
        return None

    def _build_vo_cluster_map(self) -> dict[str, type]:
        """Build a mapping of VO FQN → aggregate class by scanning fields.

        Value objects don't get ``aggregate_cluster`` set by the resolver,
        so we derive it from which aggregate/entity embeds them via
        ``ValueObject`` or ``ValueObjectList`` fields.
        """
        from protean.fields.basic import ValueObjectList
        from protean.fields.embedded import ValueObject
        from protean.utils import fqn
        from protean.utils.reflection import declared_fields

        registry = self._domain._domain_registry
        vo_map: dict[str, type] = {}

        # Scan aggregates and entities for VO field references
        for element_type in ("AGGREGATE", "ENTITY"):
            for record in registry._elements.get(element_type, {}).values():
                owner_cls = record.cls
                # For entities, use their aggregate cluster; for aggregates, use self
                agg_cls = getattr(owner_cls.meta_, "aggregate_cluster", owner_cls)

                for _name, field_obj in declared_fields(owner_cls).items():
                    if isinstance(field_obj, ValueObject):
                        vo_fqn = fqn(field_obj.value_object_cls)
                        if vo_fqn not in vo_map:
                            vo_map[vo_fqn] = agg_cls
                    elif isinstance(field_obj, ValueObjectList):
                        if isinstance(field_obj.content_type, ValueObject):
                            vo_fqn = fqn(field_obj.content_type.value_object_cls)
                        else:
                            vo_fqn = fqn(field_obj.content_type)
                        if vo_fqn not in vo_map:
                            vo_map[vo_fqn] = agg_cls

        # Also check VOs that have explicit part_of
        for record in registry._elements.get("VALUE_OBJECT", {}).values():
            vo_fqn = fqn(record.cls)
            if vo_fqn not in vo_map:
                part_of = getattr(record.cls.meta_, "part_of", None)
                if part_of is not None:
                    vo_map[vo_fqn] = part_of

        return vo_map

    def _build_clusters(self) -> dict[str, Any]:
        """Build cluster dict keyed by aggregate FQN."""
        from protean.utils import fqn

        registry = self._domain._domain_registry
        clusters: dict[str, Any] = {}

        # Build aggregate entries
        for record in registry._elements.get("AGGREGATE", {}).values():
            agg_cls = record.cls
            agg_fqn = fqn(agg_cls)

            clusters[agg_fqn] = {
                "aggregate": self._extract_aggregate(agg_cls, record),
                "application_services": {},
                "command_handlers": {},
                "commands": {},
                "database_models": {},
                "entities": {},
                "event_handlers": {},
                "events": {},
                "repositories": {},
                "value_objects": {},
            }

        # Helper to place an element into its aggregate's cluster section
        def _place_in_cluster(
            element_type_key: str, section: str, extractor: Any
        ) -> None:
            for record in registry._elements.get(element_type_key, {}).values():
                cls = record.cls
                agg_cls = self._resolve_aggregate_cls(cls)
                if agg_cls is not None:
                    agg_fqn = fqn(agg_cls)
                    if agg_fqn in clusters:
                        clusters[agg_fqn][section][fqn(cls)] = extractor(cls, record)

        _place_in_cluster("ENTITY", "entities", self._extract_entity)
        _place_in_cluster("COMMAND", "commands", self._extract_command)
        _place_in_cluster("EVENT", "events", self._extract_event)
        _place_in_cluster(
            "COMMAND_HANDLER", "command_handlers", self._extract_command_handler
        )
        _place_in_cluster(
            "EVENT_HANDLER", "event_handlers", self._extract_event_handler
        )
        _place_in_cluster(
            "APPLICATION_SERVICE",
            "application_services",
            self._extract_application_service,
        )
        _place_in_cluster("REPOSITORY", "repositories", self._extract_repository)
        _place_in_cluster(
            "DATABASE_MODEL", "database_models", self._extract_database_model
        )

        # Populate value objects (derive cluster from field references)
        vo_cluster_map = self._build_vo_cluster_map()
        for record in registry._elements.get("VALUE_OBJECT", {}).values():
            cls = record.cls
            vo_fqn = fqn(cls)
            agg_cls = vo_cluster_map.get(vo_fqn)
            if agg_cls is not None:
                agg_fqn = fqn(agg_cls)
                if agg_fqn in clusters:
                    clusters[agg_fqn]["value_objects"][vo_fqn] = (
                        self._extract_value_object(cls, record, agg_fqn)
                    )

        # Sort all inner dicts within each cluster, and sort clusters by key
        for cluster in clusters.values():
            for section in (
                "application_services",
                "command_handlers",
                "commands",
                "database_models",
                "entities",
                "event_handlers",
                "events",
                "repositories",
                "value_objects",
            ):
                cluster[section] = dict(sorted(cluster[section].items()))

        return dict(sorted(clusters.items()))

    # ------------------------------------------------------------------
    # Elements index
    # ------------------------------------------------------------------

    def _build_elements_index(self) -> dict[str, list[str]]:
        """Build elements index: {element_type: sorted([FQN, ...])}."""
        from protean.utils import fqn

        registry = self._domain._domain_registry
        # Element types to include (skip internal types)
        element_types = [
            "AGGREGATE",
            "APPLICATION_SERVICE",
            "COMMAND",
            "COMMAND_HANDLER",
            "DATABASE_MODEL",
            "DOMAIN_SERVICE",
            "ENTITY",
            "EVENT",
            "EVENT_HANDLER",
            "PROCESS_MANAGER",
            "PROJECTION",
            "PROJECTOR",
            "QUERY",
            "QUERY_HANDLER",
            "REPOSITORY",
            "SUBSCRIBER",
            "VALUE_OBJECT",
        ]

        elements: dict[str, list[str]] = {}
        for etype in element_types:
            records = registry._elements.get(etype, {})
            elements[etype] = sorted(fqn(r.cls) for r in records.values())

        return elements

    # ------------------------------------------------------------------
    # Contracts
    # ------------------------------------------------------------------

    def _build_contracts(self) -> dict[str, list[dict[str, Any]]]:
        """Build contracts section — published events with language-neutral keys.

        Contract entries use ``type`` (not ``__type__``), ``version`` (not
        ``__version__``), and include field schemas so that downstream
        consumers (schema generators, contract checkers) have everything
        they need without reaching into element-level IR.
        """
        from protean.utils import fqn

        registry = self._domain._domain_registry
        published_events: list[dict[str, Any]] = []

        for record in registry._elements.get("EVENT", {}).values():
            cls = record.cls
            if getattr(cls.meta_, "published", False):
                contract: dict[str, Any] = {
                    "fields": self._extract_fields(cls),
                    "fqn": fqn(cls),
                    "type": getattr(cls, "__type__", ""),
                    "version": getattr(cls, "__version__", 1),
                }
                deprecated = self._extract_deprecated(cls)
                if deprecated is not None:
                    contract["deprecated"] = deprecated
                published_events.append(contract)

        return {"events": sorted(published_events, key=lambda e: e.get("type", ""))}

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def _collect_diagnostics(self, ir: dict[str, Any]) -> None:
        """Collect diagnostic warnings and info findings from the built IR."""
        # Warning-level rules
        self._diagnose_unhandled_events(ir)
        self._diagnose_unused_commands(ir)
        self._diagnose_es_missing_apply(ir)
        self._diagnose_published_no_external_broker(ir)
        self._diagnose_aggregate_without_command_handler(ir)
        self._diagnose_projection_without_projector(ir)
        # Info-level rules (design smells)
        self._diagnose_aggregate_too_large(ir)
        self._diagnose_handler_too_broad(ir)
        self._diagnose_event_without_data(ir)
        self._diagnose_deprecated_elements(ir)
        # Custom lint rules from config
        self._run_custom_lint_rules(ir)

    def _diagnose_unhandled_events(self, ir: dict[str, Any]) -> None:
        """UNHANDLED_EVENT: events with no registered handler.

        Excludes published events (intentionally external), fact events
        (auto-generated), and auto-generated events (e.g. process manager
        transition events).
        """
        handled_event_types: set[str] = set()

        # Collect all handled event types from event handlers in clusters
        for cluster in ir["clusters"].values():
            for eh in cluster["event_handlers"].values():
                handled_event_types.update(eh.get("handlers", {}).keys())

        # Collect from projectors
        for proj in ir["projections"].values():
            for projector in proj["projectors"].values():
                handled_event_types.update(projector.get("handlers", {}).keys())

        # Collect from process managers
        for pm in ir["flows"]["process_managers"].values():
            handled_event_types.update(pm.get("handlers", {}).keys())

        # Check each event
        for cluster in ir["clusters"].values():
            for event in cluster["events"].values():
                # Skip published events — they are intentionally external
                if event.get("published", False):
                    continue
                # Skip fact events — auto-generated from aggregate changes
                if event.get("is_fact_event", False):
                    continue
                # Skip auto-generated events (e.g. PM transition events)
                if event.get("auto_generated", False):
                    continue

                event_type = event.get("__type__", "")
                if event_type and event_type not in handled_event_types:
                    self._diagnostics.append(
                        {
                            "code": "UNHANDLED_EVENT",
                            "element": event["fqn"],
                            "level": "warning",
                            "message": f"Event {event['name']} has no registered handler",
                        }
                    )

    def _diagnose_unused_commands(self, ir: dict[str, Any]) -> None:
        """UNUSED_COMMAND: commands with no handler method wired."""
        handled_command_types: set[str] = set()

        # Collect all handled command types from command handlers
        for cluster in ir["clusters"].values():
            for ch in cluster["command_handlers"].values():
                handled_command_types.update(ch.get("handlers", {}).keys())

        # Check each command
        for cluster in ir["clusters"].values():
            for command in cluster["commands"].values():
                command_type = command.get("__type__", "")
                if command_type and command_type not in handled_command_types:
                    self._diagnostics.append(
                        {
                            "code": "UNUSED_COMMAND",
                            "element": command["fqn"],
                            "level": "warning",
                            "message": f"Command {command['name']} has no registered handler",
                        }
                    )

    def _diagnose_es_missing_apply(self, ir: dict[str, Any]) -> None:
        """ES_EVENT_MISSING_APPLY: ES aggregate events without @apply handler.

        For event-sourced aggregates, every domain event (excluding fact
        events and auto-generated events) should have a corresponding
        @apply handler on the aggregate.
        """
        for cluster in ir["clusters"].values():
            aggregate = cluster["aggregate"]
            options = aggregate.get("options", {})

            if not options.get("is_event_sourced", False):
                continue

            apply_handlers = aggregate.get("apply_handlers", {})

            for event in cluster["events"].values():
                # Skip fact events and auto-generated events
                if event.get("is_fact_event", False):
                    continue
                if event.get("auto_generated", False):
                    continue

                event_fqn = event["fqn"]
                if event_fqn not in apply_handlers:
                    self._diagnostics.append(
                        {
                            "code": "ES_EVENT_MISSING_APPLY",
                            "element": event_fqn,
                            "level": "warning",
                            "message": (
                                f"Event {event['name']} has no @apply handler "
                                f"on aggregate {aggregate['name']}"
                            ),
                        }
                    )

    def _diagnose_published_no_external_broker(self, ir: dict[str, Any]) -> None:
        """PUBLISHED_NO_EXTERNAL_BROKER: published events without external brokers.

        When events are marked as ``published`` but no external brokers are
        configured, they will only be dispatched internally — which is likely
        not the intent.
        """
        external_brokers = self._domain.config.get("outbox", {}).get(
            "external_brokers", []
        )
        if external_brokers:
            return

        has_published = any(
            event.get("published", False)
            for cluster in ir["clusters"].values()
            for event in cluster["events"].values()
        )
        if has_published:
            self._diagnostics.append(
                {
                    "code": "PUBLISHED_NO_EXTERNAL_BROKER",
                    "element": self._domain.name,
                    "level": "warning",
                    "message": (
                        "Domain has published events but no external_brokers "
                        "configured in outbox settings. Published events will "
                        "only be dispatched internally."
                    ),
                }
            )

    def _diagnose_aggregate_without_command_handler(self, ir: dict[str, Any]) -> None:
        """AGGREGATE_WITHOUT_COMMAND_HANDLER: aggregate with no write path.

        An aggregate cluster that has no command handlers has no way to
        receive commands — likely a wiring gap.  Internal/infrastructure
        aggregates (from ``protean.adapters``) are excluded.
        """
        for cluster in ir["clusters"].values():
            aggregate = cluster["aggregate"]
            # Skip infrastructure aggregates (e.g. MemoryMessage)
            if aggregate["fqn"].startswith("protean.adapters."):
                continue
            if not cluster["command_handlers"]:
                self._diagnostics.append(
                    {
                        "code": "AGGREGATE_WITHOUT_COMMAND_HANDLER",
                        "element": aggregate["fqn"],
                        "level": "warning",
                        "message": (
                            f"Aggregate `{aggregate['name']}` has no command handler "
                            f"— no write path exists"
                        ),
                    }
                )

    def _diagnose_projection_without_projector(self, ir: dict[str, Any]) -> None:
        """PROJECTION_WITHOUT_PROJECTOR: projection with no projector to populate it."""
        for proj_entry in ir["projections"].values():
            if not proj_entry["projectors"]:
                proj = proj_entry["projection"]
                self._diagnostics.append(
                    {
                        "code": "PROJECTION_WITHOUT_PROJECTOR",
                        "element": proj["fqn"],
                        "level": "warning",
                        "message": (
                            f"Projection `{proj['name']}` has no projector "
                            f"to populate it"
                        ),
                    }
                )

    # ------------------------------------------------------------------
    # Info-level diagnostics (design smells)
    # ------------------------------------------------------------------

    def _diagnose_aggregate_too_large(self, ir: dict[str, Any]) -> None:
        """AGGREGATE_TOO_LARGE: cluster with too many entities.

        Configurable via ``[lint] aggregate_size_limit`` in domain config
        (default 5).
        """
        limit = self._domain.config.get("lint", {}).get("aggregate_size_limit", 5)
        for cluster in ir["clusters"].values():
            aggregate = cluster["aggregate"]
            # Skip infrastructure aggregates
            if aggregate["fqn"].startswith("protean.adapters."):
                continue
            entity_count = len(cluster["entities"])
            if entity_count > limit:
                self._diagnostics.append(
                    {
                        "code": "AGGREGATE_TOO_LARGE",
                        "element": aggregate["fqn"],
                        "level": "info",
                        "message": (
                            f"Aggregate `{aggregate['name']}` has {entity_count} "
                            f"entities (limit: {limit})"
                        ),
                    }
                )

    def _diagnose_handler_too_broad(self, ir: dict[str, Any]) -> None:
        """HANDLER_TOO_BROAD: handler handling too many message types.

        Configurable via ``[lint] handler_breadth_limit`` in domain config
        (default 5).
        """
        limit = self._domain.config.get("lint", {}).get("handler_breadth_limit", 5)
        for cluster in ir["clusters"].values():
            # Check command handlers
            for ch in cluster["command_handlers"].values():
                handler_count = len(ch.get("handlers", {}))
                if handler_count > limit:
                    self._diagnostics.append(
                        {
                            "code": "HANDLER_TOO_BROAD",
                            "element": ch["fqn"],
                            "level": "info",
                            "message": (
                                f"Handler `{ch['name']}` handles {handler_count} "
                                f"message types (limit: {limit})"
                            ),
                        }
                    )
            # Check event handlers
            for eh in cluster["event_handlers"].values():
                handler_count = len(eh.get("handlers", {}))
                if handler_count > limit:
                    self._diagnostics.append(
                        {
                            "code": "HANDLER_TOO_BROAD",
                            "element": eh["fqn"],
                            "level": "info",
                            "message": (
                                f"Handler `{eh['name']}` handles {handler_count} "
                                f"message types (limit: {limit})"
                            ),
                        }
                    )

    def _diagnose_event_without_data(self, ir: dict[str, Any]) -> None:
        """EVENT_WITHOUT_DATA: event with zero user-defined fields.

        An event with no fields carries no information beyond its type name.
        This is usually a mistake — events should capture the relevant state
        change data.  Auto-generated fields (id, _metadata) are excluded.
        """
        auto_field_names = {"id", "_metadata"}
        for cluster in ir["clusters"].values():
            for event in cluster["events"].values():
                # Skip fact events and auto-generated events
                if event.get("is_fact_event", False):
                    continue
                if event.get("auto_generated", False):
                    continue
                user_fields = {
                    name
                    for name in event.get("fields", {})
                    if name not in auto_field_names
                }
                if not user_fields:
                    self._diagnostics.append(
                        {
                            "code": "EVENT_WITHOUT_DATA",
                            "element": event["fqn"],
                            "level": "info",
                            "message": (
                                f"Event `{event['name']}` has no user-defined fields"
                            ),
                        }
                    )

    def _diagnose_deprecated_elements(self, ir: dict[str, Any]) -> None:
        """DEPRECATED_ELEMENT: elements or fields marked as deprecated.

        Reports deprecated elements and deprecated fields as INFO-level
        diagnostics so that ``protean check`` surfaces them.
        """
        _subsections = (
            "entities",
            "value_objects",
            "commands",
            "events",
            "command_handlers",
            "event_handlers",
            "repositories",
            "database_models",
            "application_services",
        )

        # Scan clusters (aggregates + sub-elements)
        for cluster in ir["clusters"].values():
            self._check_element_deprecated(cluster["aggregate"])
            for section in _subsections:
                for element in cluster.get(section, {}).values():
                    self._check_element_deprecated(element)

        # Scan projections
        for proj_entry in ir["projections"].values():
            self._check_element_deprecated(proj_entry["projection"])
            for section in ("projectors", "queries", "query_handlers"):
                for element in proj_entry.get(section, {}).values():
                    self._check_element_deprecated(element)

        # Scan flows
        for section in ("domain_services", "process_managers", "subscribers"):
            for element in ir["flows"].get(section, {}).values():
                self._check_element_deprecated(element)

    def _check_element_deprecated(self, element: dict[str, Any]) -> None:
        """Emit DEPRECATED_ELEMENT / DEPRECATED_FIELD diagnostics."""
        name = element.get("name", element.get("fqn", "unknown"))
        fqn_val = element.get("fqn", name)

        # Element-level deprecation
        deprecated = element.get("deprecated")
        if deprecated is not None:
            since = deprecated.get("since", "?")
            removal = deprecated.get("removal")
            if removal:
                msg = (
                    f"`{name}` is deprecated since v{since}, "
                    f"scheduled for removal in v{removal}"
                )
            else:
                msg = f"`{name}` is deprecated since v{since}"

            self._diagnostics.append(
                {
                    "code": "DEPRECATED_ELEMENT",
                    "element": fqn_val,
                    "level": "info",
                    "message": msg,
                }
            )

        # Field-level deprecation (independent of element deprecation)
        for field_name, field_info in element.get("fields", {}).items():
            field_deprecated = field_info.get("deprecated")
            if field_deprecated is not None:
                f_since = field_deprecated.get("since", "?")
                f_removal = field_deprecated.get("removal")
                if f_removal:
                    f_msg = (
                        f"Field `{name}.{field_name}` is deprecated since "
                        f"v{f_since}, scheduled for removal in v{f_removal}"
                    )
                else:
                    f_msg = (
                        f"Field `{name}.{field_name}` is deprecated since "
                        f"v{f_since}"
                    )
                self._diagnostics.append(
                    {
                        "code": "DEPRECATED_FIELD",
                        "element": fqn_val,
                        "field": field_name,
                        "level": "info",
                        "message": f_msg,
                    }
                )

    # ------------------------------------------------------------------
    # Custom lint rules
    # ------------------------------------------------------------------

    _VALID_LEVELS = frozenset({"warning", "info"})
    _REQUIRED_KEYS = frozenset({"code", "element", "level", "message"})

    def _run_custom_lint_rules(self, ir: dict[str, Any]) -> None:
        """Run user-defined lint rules from ``[lint] rules`` in domain config.

        Each entry is a dotted import path to a callable with the signature
        ``(ir: dict) -> list[dict]``.  Each returned dict must contain the
        keys ``code``, ``element``, ``level``, and ``message``.  Invalid
        results are logged and skipped.  Exceptions in rules are caught so
        they never crash ``protean check``.
        """
        import logging

        logger = logging.getLogger(__name__)

        rule_paths: list[str] = self._domain.config.get("lint", {}).get("rules", [])
        if not rule_paths:
            return

        for path in rule_paths:
            try:
                callable_fn = self._import_callable(path)
            except Exception:
                logger.warning(
                    "Custom lint rule %r could not be imported — skipped", path
                )
                continue

            try:
                results = callable_fn(ir)
            except Exception:
                logger.warning(
                    "Custom lint rule %r raised an exception — skipped", path
                )
                continue

            if not isinstance(results, list):
                logger.warning(
                    "Custom lint rule %r returned %s instead of list — skipped",
                    path,
                    type(results).__name__,
                )
                continue

            for item in results:
                if not isinstance(item, dict):
                    logger.warning(
                        "Custom lint rule %r returned non-dict item — skipped", path
                    )
                    continue
                missing = self._REQUIRED_KEYS - set(item)
                if missing:
                    logger.warning(
                        "Custom lint rule %r returned item missing keys %s — skipped",
                        path,
                        missing,
                    )
                    continue
                if item["level"] not in self._VALID_LEVELS:
                    logger.warning(
                        "Custom lint rule %r returned invalid level %r — skipped",
                        path,
                        item["level"],
                    )
                    continue
                self._diagnostics.append(item)

    @staticmethod
    def _import_callable(dotted_path: str) -> Any:
        """Import a callable from a dotted path like ``'my_app.lint.check_names'``."""
        import importlib

        module_path, _, attr_name = dotted_path.rpartition(".")
        if not module_path:
            raise ImportError(f"Invalid dotted path: {dotted_path!r}")
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)

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
