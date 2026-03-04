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
        entry["__version__"] = getattr(cls, "__version__", "v1")
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
        entry["__version__"] = getattr(cls, "__version__", "v1")

        if record.auto_generated:
            entry["auto_generated"] = True

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
        entry["database"] = getattr(cls.meta_, "database", None)
        entry["element_type"] = "DATABASE_MODEL"
        entry["fqn"] = fqn(cls)
        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        agg_cls = self._resolve_aggregate_cls(cls)
        if agg_cls is not None:
            entry["part_of"] = fqn(agg_cls)

        entry["schema_name"] = getattr(cls.meta_, "schema_name", None)

        return dict(sorted(entry.items()))

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
    # Checksum
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_checksum(ir: dict[str, Any]) -> str:
        """SHA-256 of canonical JSON with volatile keys removed."""
        ir_copy = {k: v for k, v in ir.items() if k not in ("generated_at", "checksum")}
        canonical = json.dumps(ir_copy, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"
