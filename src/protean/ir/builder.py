"""IRBuilder — walks a Domain composite root and produces an IR dict.

Usage::

    from protean.ir.builder import IRBuilder

    domain.init()
    ir = IRBuilder(domain).build()
"""

from __future__ import annotations

import ast
import datetime as _dt
import hashlib
import importlib
import importlib.util
import json
import logging
import types as _types
import typing
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from protean.core.aggregate import BaseAggregate
from protean.core.index import Index, RawIndex
from protean.exceptions import ConfigurationError
from protean.fields.association import HasMany, HasOne, Reference
from protean.fields.basic import ValueObjectList
from protean.fields.embedded import ValueObject
from protean.fields.resolved import ResolvedField
from protean.fields.spec import _UNSET
from protean.ir import SCHEMA_VERSION
from protean.ir.constants import VOLATILE_IR_KEYS
from protean.utils import fqn
from protean.utils.container import Element, OptionsMixin
from protean.utils.reflection import _ID_FIELD_NAME, declared_fields
from protean.utils.upcasting import (
    missing_upcaster_source_versions,
    upcaster_event_name,
)

if TYPE_CHECKING:
    from protean.domain import Domain

    class _ElementCls(Element, OptionsMixin):
        """Static-only view of a registered domain element class.

        Every element base (``BaseEntity``, ``BaseValueObject``,
        ``BaseCommandHandler``, ...) inherits both :class:`Element` (nominal
        base expected by :func:`declared_fields`/:func:`fqn`) and
        :class:`OptionsMixin` (which carries the injected ``meta_`` metadata).
        No single runtime class combines the two, so this TYPE_CHECKING-only
        class gives the extractor methods a param type that both checkers can
        follow to ``cls.meta_`` and the reflection helpers at once. It has no
        runtime effect.
        """


def validate_lint_suppressions(suppressions: Any) -> str | None:
    """Return an error message if ``[lint].suppressions`` is malformed, else ``None``.

    ``[lint].suppressions`` must be a table mapping diagnostic codes to
    non-negative integer counts (``{CODE: N}``). Without this guard a
    non-integer value crashes the IR build with a bare ``TypeError`` /
    ``AttributeError`` at *every* entry point that builds the IR (``protean
    check``, ``protean generate``, the pre-commit/materialize hooks, staleness
    detection) — see :meth:`IRBuilder._apply_suppressions`. Callers surface the
    returned message in whatever form suits them (a CLI error, a raised
    :class:`ConfigurationError`).
    """
    if not isinstance(suppressions, dict):
        return (
            "[lint].suppressions must be a table of {code: count}, got "
            f"{type(suppressions).__name__}."
        )
    for code, count in suppressions.items():
        # ``bool`` is an ``int`` subclass — reject it explicitly so a stray
        # ``CODE = true`` is not silently read as ``1``.
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return (
                f"[lint].suppressions.{code} must be a non-negative integer, "
                f"got {count!r}."
            )
    return None


def validate_lint_table(lint_config: Any) -> str | None:
    """Return an error message if ``[lint]`` itself is not a table, else ``None``.

    Every ``[lint]``-scoped setting (``level``, ``suppressions``,
    ``aggregate_size_limit``, ``handler_breadth_limit``, ``rules``, ...) is read
    via ``domain.config.get("lint", {}).get(<key>, ...)``. If a user sets
    ``[lint]`` itself to a non-table (e.g. ``lint = 5``), that first ``.get(...)``
    raises a bare ``AttributeError`` before any of those individual reads —
    including :func:`validate_lint_suppressions` — get a chance to run. Callers
    must check this *before* reading any ``[lint]`` key.
    """
    if not isinstance(lint_config, dict):
        return f"[lint] must be a table, got {type(lint_config).__name__}."
    return None


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
            "generated_at": datetime.now(_dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ir_version": SCHEMA_VERSION,
            "projections": self._build_projections(),
        }

        # Sparse: only project upcasters when the domain has any, so
        # upcaster-free domains keep a byte-identical IR (and checksum).
        upcasters = self._build_upcasters()
        if upcasters:
            ir["upcasters"] = upcasters

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
    def _extract_deprecated(cls: type[_ElementCls]) -> dict[str, str] | None:
        """Return the normalized ``deprecated`` metadata from an element's meta_.

        Returns ``None`` when the element is not deprecated (sparse IR).
        """
        return getattr(getattr(cls, "meta_", None), "deprecated", None)

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _resolved_fqn(target: type | str) -> str:
        """Return the FQN of an association/VO target class.

        Association (``HasOne``/``HasMany``/``Reference``) and embedded
        (``ValueObject``) fields carry their target as either a concrete class
        or, before resolution, a string name. IRBuilder runs against an
        initialised domain (its documented precondition), so every target has
        been resolved to a class by this point; the ``str`` branch is a
        defensive guard, not an expected path.
        """
        assert not isinstance(target, str), (
            f"unresolved target {target!r}; IRBuilder requires an initialised domain"
        )
        return fqn(target)

    def _extract_fields(self, cls: type[_ElementCls]) -> dict[str, Any]:
        """Extract field definitions from a domain element class.

        Returns a dict keyed by field name, each value a sparse IR field dict.
        """

        result: dict[str, Any] = {}
        field_meta: dict[str, Any] = getattr(cls, "__protean_field_meta__", {})

        for name, field_obj in sorted(declared_fields(cls).items()):
            entry: dict[str, Any] = {}

            if isinstance(field_obj, ValueObject):
                entry["kind"] = "value_object"
                entry["target"] = self._resolved_fqn(field_obj.value_object_cls)
                if field_obj.required:
                    entry["required"] = True

            elif isinstance(field_obj, ValueObjectList):
                entry["kind"] = "value_object_list"
                if isinstance(field_obj.content_type, ValueObject):
                    entry["target"] = self._resolved_fqn(
                        field_obj.content_type.value_object_cls
                    )
                else:
                    entry["target"] = fqn(field_obj.content_type)

            elif isinstance(field_obj, HasOne):
                entry["kind"] = "has_one"
                entry["target"] = self._resolved_fqn(field_obj.to_cls)
                if field_obj.via is not None:
                    entry["via"] = field_obj.via

            elif isinstance(field_obj, HasMany):
                entry["kind"] = "has_many"
                entry["target"] = self._resolved_fqn(field_obj.to_cls)
                if field_obj.via is not None:
                    entry["via"] = field_obj.via

            elif isinstance(field_obj, Reference):
                entry["kind"] = "reference"
                entry["target"] = self._resolved_fqn(field_obj.to_cls)
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

            # Renamed-from — carried on the field object for both classic
            # ``Field`` and ``ResolvedField`` (unlike ``deprecated``), so it can
            # be emitted uniformly here for every field type.
            renamed_from = getattr(field_obj, "renamed_from", None)
            if renamed_from:
                entry["renamed_from"] = renamed_from

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
            choices: Any = spec.choices
            if isinstance(choices, type) and issubclass(choices, Enum):
                choices_list = sorted(item.value for item in choices)
            else:
                choices_iter: Any = choices
                choices_list = sorted(str(c) for c in choices_iter)
            entry["choices"] = choices_list

        # Transitions — from ResolvedField
        if getattr(field, "transitions", None) is not None:
            entry["transitions"] = field.transitions

        # Deprecated — from FieldSpec
        if spec is not None and getattr(spec, "deprecated", None) is not None:
            entry["deprecated"] = spec.deprecated

        # Default — from FieldSpec for accurate representation
        if spec is not None:
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
        if python_type is None:
            return False
        return typing.get_origin(python_type) is list

    @staticmethod
    def _is_dict_type(base_type: type | None, original_type: type | None) -> bool:
        """Check if a type is a dict.

        Handles both ``dict`` and ``dict | list`` (from Dict() field).
        """
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

    def _extract_invariants(self, cls: type[_ElementCls]) -> dict[str, list[str]]:
        """Extract pre/post invariant method names as sorted lists."""
        invariants = getattr(cls, "_invariants", {})
        return {
            "post": sorted(invariants.get("post", {}).keys()),
            "pre": sorted(invariants.get("pre", {}).keys()),
        }

    def _extract_indexes(self, cls: type[_ElementCls]) -> list[dict[str, Any]]:
        """Extract a JSON-safe summary of an element's index declarations.

        The ``where`` partial predicate is summarized as ``partial: true``
        rather than serialized; the rendered DDL (via ``protean schema render
        --indexes``) carries the exact predicate.
        """
        declared = getattr(getattr(cls, "meta_", None), "indexes", ()) or ()
        result: list[dict[str, Any]] = []
        for idx in declared:
            if isinstance(idx, RawIndex):
                raw_entry: dict[str, Any] = {
                    "raw": True,
                    "dialect": idx.dialect,
                    "ddl": idx.ddl,
                }
                if idx.name:
                    raw_entry["name"] = idx.name
                result.append(raw_entry)
            elif isinstance(idx, Index):
                entry: dict[str, Any] = {
                    "fields": list(idx.fields),
                    "unique": idx.unique,
                }
                if idx.name:
                    entry["name"] = idx.name
                if idx.desc:
                    entry["desc"] = list(idx.desc)
                if idx.include:
                    entry["include"] = list(idx.include)
                if idx.where is not None:
                    entry["partial"] = True
                result.append(entry)
        return result

    def _extract_aggregate(self, cls: type[_ElementCls], record: Any) -> dict[str, Any]:
        """Extract aggregate IR dict."""
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

        indexes = self._extract_indexes(cls)
        if indexes:
            entry["indexes"] = indexes

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

    def _extract_entity(self, cls: type[_ElementCls], record: Any) -> dict[str, Any]:
        """Extract entity IR dict."""
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

        indexes = self._extract_indexes(cls)
        if indexes:
            entry["indexes"] = indexes

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
        self, cls: type[_ElementCls], record: Any, aggregate_fqn: str | None = None
    ) -> dict[str, Any]:
        """Extract value object IR dict."""
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

    def _extract_command(self, cls: type[_ElementCls], record: Any) -> dict[str, Any]:
        """Extract command IR dict."""
        entry: dict[str, Any] = {}
        entry["__type__"] = getattr(cls, "__type__", "")
        entry["__version__"] = getattr(cls, "__version__", 1)

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        # Sparse: only present when the command was declared with a deprecated
        # event-only option (``published``/``is_fact_event``). ``command_factory``
        # drops the option but records it here so ``protean check`` can flag it.
        deprecated_options = getattr(cls, "_deprecated_options", None)
        if deprecated_options:
            entry["deprecated_options"] = sorted(deprecated_options)

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

    def _extract_event(self, cls: type[_ElementCls], record: Any) -> dict[str, Any]:
        """Extract event IR dict."""
        entry: dict[str, Any] = {}
        entry["__type__"] = getattr(cls, "__type__", "")
        entry["__version__"] = getattr(cls, "__version__", 1)

        if record.auto_generated:
            entry["auto_generated"] = True

        deprecated = self._extract_deprecated(cls)
        if deprecated is not None:
            entry["deprecated"] = deprecated

        superseded_by = getattr(cls.meta_, "superseded_by", None)
        if superseded_by is not None:
            entry["superseded_by"] = (
                fqn(superseded_by) if isinstance(superseded_by, type) else superseded_by
            )

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

    @staticmethod
    def _extract_resilience_policy(cls: type[_ElementCls]) -> dict[str, Any] | None:
        """Extract the handler's deadline/retry policy as a sparse IR dict.

        Returns ``None`` when no resilience options are set (sparse IR).
        """
        meta = getattr(cls, "meta_", None)
        policy: dict[str, Any] = {}

        timeout = getattr(meta, "timeout", None)
        if timeout is not None:
            if isinstance(timeout, _dt.timedelta):
                policy["timeout"] = timeout.total_seconds()
            else:
                policy["timeout"] = float(timeout)

        for key in ("backoff", "retries"):
            value = getattr(meta, key, None)
            if value is not None:
                policy[key] = value

        retry_exceptions = getattr(meta, "retry_exceptions", None)
        if retry_exceptions is not None:
            names: list[str] = []
            for exc in retry_exceptions:
                if isinstance(exc, str):
                    names.append(exc)
                elif isinstance(exc, type):
                    names.append(fqn(exc))
                else:
                    # Misconfigured entry (e.g. an exception instance rather
                    # than its class) — serialize its class instead of
                    # crashing IR materialization with an opaque AttributeError.
                    names.append(fqn(type(exc)))
            policy["retry_exceptions"] = sorted(names)

        return dict(sorted(policy.items())) if policy else None

    def _extract_handler_map(self, cls: type[_ElementCls]) -> dict[str, list[str]]:
        """Extract handler map as {__type__: sorted([method_names])}."""
        handlers = getattr(cls, "_handlers", {})
        result: dict[str, list[str]] = {}
        for type_key, methods in sorted(handlers.items()):
            if methods:
                result[type_key] = sorted(m.__name__ for m in methods)
        return result

    def _extract_subscription(self, cls: type[_ElementCls]) -> dict[str, Any]:
        """Extract subscription config as {type, profile, config}."""
        sub_type = getattr(cls.meta_, "subscription_type", None)
        sub_profile = getattr(cls.meta_, "subscription_profile", None)
        sub_config = getattr(cls.meta_, "subscription_config", {})
        return {
            "config": sub_config if sub_config else {},
            "profile": sub_profile.value if sub_profile else None,
            "type": sub_type.value if sub_type else None,
        }

    def _extract_command_handler(
        self, cls: type[_ElementCls], record: Any
    ) -> dict[str, Any]:
        """Extract command handler IR dict."""
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

        resilience = self._extract_resilience_policy(cls)
        if resilience is not None:
            entry["resilience"] = resilience

        entry["stream_category"] = getattr(cls.meta_, "stream_category", None)
        entry["subscription"] = self._extract_subscription(cls)

        return dict(sorted(entry.items()))

    def _extract_event_handler(
        self, cls: type[_ElementCls], record: Any
    ) -> dict[str, Any]:
        """Extract event handler IR dict."""
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

        resilience = self._extract_resilience_policy(cls)
        if resilience is not None:
            entry["resilience"] = resilience

        entry["source_stream"] = getattr(cls.meta_, "source_stream", None)
        entry["stream_category"] = getattr(cls.meta_, "stream_category", None)
        entry["subscription"] = self._extract_subscription(cls)

        return dict(sorted(entry.items()))

    def _extract_application_service(
        self, cls: type[_ElementCls], record: Any
    ) -> dict[str, Any]:
        """Extract application service IR dict."""
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

    def _extract_repository(
        self, cls: type[_ElementCls], record: Any
    ) -> dict[str, Any]:
        """Extract repository IR dict."""
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

    def _extract_database_model(
        self, cls: type[_ElementCls], record: Any
    ) -> dict[str, Any]:
        """Extract database model IR dict."""
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

    def _extract_projection(
        self, cls: type[_ElementCls], record: Any
    ) -> dict[str, Any]:
        """Extract projection IR dict."""
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

        indexes = self._extract_indexes(cls)
        if indexes:
            entry["indexes"] = indexes

        entry["module"] = cls.__module__
        entry["name"] = cls.__name__

        order_by = getattr(cls.meta_, "order_by", ())
        entry["options"] = dict(
            sorted(
                {
                    "cache": getattr(cls.meta_, "cache", None),
                    "externally_populated": getattr(
                        cls.meta_, "externally_populated", False
                    ),
                    "limit": getattr(cls.meta_, "limit", 100),
                    "order_by": list(order_by) if order_by else [],
                    "provider": getattr(cls.meta_, "provider", "default"),
                    "schema_name": getattr(cls.meta_, "schema_name", None),
                }.items()
            )
        )

        return dict(sorted(entry.items()))

    def _extract_projector(self, cls: type[_ElementCls], record: Any) -> dict[str, Any]:
        """Extract projector IR dict."""
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

    def _extract_query(self, cls: type[_ElementCls], record: Any) -> dict[str, Any]:
        """Extract query IR dict."""
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

    def _extract_query_handler(
        self, cls: type[_ElementCls], record: Any
    ) -> dict[str, Any]:
        """Extract query handler IR dict."""
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

    def _extract_domain_service(
        self, cls: type[_ElementCls], record: Any
    ) -> dict[str, Any]:
        """Extract domain service IR dict."""
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

    def _extract_process_manager(
        self, cls: type[_ElementCls], record: Any
    ) -> dict[str, Any]:
        """Extract process manager IR dict."""
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

    def _extract_subscriber(
        self, cls: type[_ElementCls], record: Any
    ) -> dict[str, Any]:
        """Extract subscriber IR dict."""
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
    def _resolve_aggregate_cls(cls: type[_ElementCls]) -> type | None:
        """Resolve the root aggregate class for an element.

        Tries ``aggregate_cluster`` first (set by resolver for entities,
        commands, events), then falls back to traversing ``part_of``
        (needed for fact events generated after cluster assignment).
        """

        agg: type | None = getattr(cls.meta_, "aggregate_cluster", None)
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
        registry = self._domain._domain_registry
        vo_map: dict[str, type] = {}

        # Scan aggregates and entities for VO field references
        for element_type in ("AGGREGATE", "ENTITY"):
            for record in registry._elements.get(element_type, {}).values():
                owner_cls = record.cls
                # For entities, use their aggregate cluster; for aggregates, use self
                agg_cls = getattr(owner_cls.meta_, "aggregate_cluster", owner_cls)

                for field_obj in declared_fields(owner_cls).values():
                    if isinstance(field_obj, ValueObject):
                        vo_fqn = self._resolved_fqn(field_obj.value_object_cls)
                        if vo_fqn not in vo_map:
                            vo_map[vo_fqn] = agg_cls
                    elif isinstance(field_obj, ValueObjectList):
                        if isinstance(field_obj.content_type, ValueObject):
                            vo_fqn = self._resolved_fqn(
                                field_obj.content_type.value_object_cls
                            )
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
        registry = self._domain._domain_registry
        clusters: dict[str, Any] = {}

        # Build aggregate entries (skip internal framework aggregates like Outbox)
        for record in registry._elements.get("AGGREGATE", {}).values():
            if record.internal:
                continue

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
            "UPCASTER",
            "VALUE_OBJECT",
        ]

        elements: dict[str, list[str]] = {}
        for etype in element_types:
            records = registry._elements.get(etype, {})
            elements[etype] = sorted(
                fqn(r.cls) for r in records.values() if not r.internal
            )

        return elements

    def _build_upcasters(self) -> dict[str, list[dict[str, int]]]:
        """Project registered upcaster chains into the IR.

        Keyed by event base name (matching the ``Domain.Name`` type string and
        ``_diagnose_upcaster_gap``) → sorted ``from_version``/``to_version``
        edges, so the compatibility checker can tell whether an upcaster covers
        an event's version bump without a live domain. Emitted only when
        upcasters exist, so upcaster-free domains keep a byte-identical IR.
        """
        edges_by_event: dict[str, list[dict[str, int]]] = {}
        for upcaster_cls in self._domain._upcasters:
            name = upcaster_event_name(upcaster_cls.meta_.event_type)
            edges_by_event.setdefault(name, []).append(
                {
                    "from_version": upcaster_cls.meta_.from_version,
                    "to_version": upcaster_cls.meta_.to_version,
                }
            )
        return {
            name: sorted(edges, key=lambda e: (e["from_version"], e["to_version"]))
            for name, edges in sorted(edges_by_event.items())
        }

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
        # Guard the whole ``[lint]`` table up front — every rule below reads
        # ``self._domain.config.get("lint", {})``, so a malformed non-table
        # value must fail here with a clear error, not as a bare
        # AttributeError from whichever rule happens to read it first.
        lint_error = validate_lint_table(self._domain.config.get("lint", {}))
        if lint_error:
            raise ConfigurationError(lint_error)

        # Warning-level rules
        self._diagnose_unhandled_events(ir)
        self._diagnose_unused_commands(ir)
        self._diagnose_es_missing_apply(ir)
        self._diagnose_published_no_external_broker(ir)
        self._diagnose_aggregate_without_command_handler(ir)
        self._diagnose_projection_without_projector(ir)
        self._diagnose_upcaster_gap(ir)
        self._diagnose_cross_aggregate_reference(ir)
        self._diagnose_es_aggregate_no_events(ir)
        self._diagnose_value_object_mutable_field(ir)
        self._diagnose_circular_cluster_dependencies(ir)
        self._diagnose_infra_imports(ir)
        self._diagnose_query_handler_without_query(ir)
        self._diagnose_projector_handles_orphaned_event(ir)
        self._diagnose_command_handler_cross_cluster(ir)
        # Info-level rules (design smells)
        self._diagnose_aggregate_too_large(ir)
        self._diagnose_handler_too_broad(ir)
        self._diagnose_event_without_data(ir)
        self._diagnose_subscriber_no_streams(ir)
        self._diagnose_process_manager_unclosed(ir)
        self._diagnose_deprecated_elements(ir)
        self._diagnose_deprecated_options(ir)
        self._diagnose_email_deprecated(ir)
        self._diagnose_aggregate_no_invariants(ir)
        # Custom lint rules from config
        self._run_custom_lint_rules(ir)
        # Suppression stage — runs last so custom-rule findings are also
        # subject to per-element ``suppress_checks`` and ``[lint].suppressions``.
        self._apply_suppressions()

    def _diagnose_circular_cluster_dependencies(self, ir: dict[str, Any]) -> None:
        """CIRCULAR_CLUSTER_DEPENDENCY: aggregate clusters whose cross-aggregate
        identity references form a directed cycle.

        Edges are genuine inter-cluster dependencies only: a field of
        kind "reference" whose target is another cluster's aggregate root. The
        within-aggregate child->root back-pointer (auto-generated Reference) and
        any intra-cluster reference are excluded by the ``target != cluster_fqn``
        guard, because every element in a cluster shares that cluster's FQN.

        Cyclic clusters are found by strongly-connected-component membership,
        not by first-cycle discovery: every cluster in a strongly-connected
        component of size >= 2 is mutually reachable from every other, so each
        is genuinely part of a directed cycle and is reported exactly once —
        even when it sits on a second cycle or is only reachable through an
        already-finalized node. Node and neighbour orderings are sorted, so the
        reported set and message are deterministic.
        """
        cluster_fqns = set(ir["clusters"].keys())

        # 1. Build adjacency: cluster_fqn -> sorted list of target cluster FQNs.
        adjacency: dict[str, list[str]] = {}
        for cluster_fqn, cluster in ir["clusters"].items():
            targets: set[str] = set()
            entities = [cluster["aggregate"], *cluster["entities"].values()]
            for element in entities:
                for field in element.get("fields", {}).values():
                    if field.get("kind") != "reference":
                        continue
                    target = field.get("target")
                    if target in cluster_fqns and target != cluster_fqn:
                        targets.add(target)
            adjacency[cluster_fqn] = sorted(targets)

        # 2. One diagnostic per cluster in each cyclic component. A component of
        #    size >= 2 is exactly the set of mutually-dependent clusters (a
        #    self-loop is impossible here — ``target != cluster_fqn`` guards it).
        for component in self._strongly_connected_components(adjacency):
            if len(component) >= 2:
                self._emit_cluster_cycle(component)

    @staticmethod
    def _strongly_connected_components(
        adjacency: dict[str, list[str]],
    ) -> list[list[str]]:
        """Tarjan's SCC algorithm, iterative (no recursion-limit risk on deep
        graphs).

        Returns each strongly-connected component as a sorted member list, and
        the components themselves in sorted order, so the caller emits a stable,
        byte-identical result across builds. Every node appears in exactly one
        component, so a cluster on two overlapping cycles is reported once.
        """
        index_of: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        on_stack: dict[str, bool] = {}
        tarjan_stack: list[str] = []
        components: list[list[str]] = []
        counter = 0

        for start in sorted(adjacency):
            if start in index_of:
                continue
            # Explicit work stack of [node, next-neighbour-index] frames.
            work: list[list[Any]] = [[start, 0]]
            while work:
                node, i = work[-1]
                if i == 0:
                    index_of[node] = lowlink[node] = counter
                    counter += 1
                    tarjan_stack.append(node)
                    on_stack[node] = True
                neighbours = adjacency[node]
                recursed = False
                while i < len(neighbours):
                    nxt = neighbours[i]
                    i += 1
                    if nxt not in index_of:
                        work[-1][1] = i  # resume after this neighbour
                        work.append([nxt, 0])
                        recursed = True
                        break
                    if on_stack.get(nxt):
                        lowlink[node] = min(lowlink[node], index_of[nxt])
                if recursed:
                    continue
                # Node fully explored: close a component if it is a root.
                if lowlink[node] == index_of[node]:
                    component: list[str] = []
                    while True:
                        w = tarjan_stack.pop()
                        on_stack[w] = False
                        component.append(w)
                        if w == node:
                            break
                    components.append(sorted(component))
                work.pop()
                if work:  # propagate lowlink up to the parent frame
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])

        return sorted(components)

    def _emit_cluster_cycle(self, component: list[str]) -> None:
        """Append one CIRCULAR_CLUSTER_DEPENDENCY diagnostic per cluster in the
        strongly-connected component, naming the whole mutually-dependent group
        so the reported set is stable and each cluster is reported once."""
        group = ", ".join(f"`{fqn}`" for fqn in component)
        for cluster_fqn in component:
            self._diagnostics.append(
                {
                    "code": "CIRCULAR_CLUSTER_DEPENDENCY",
                    "category": "bounded_context",
                    "element": cluster_fqn,
                    "level": "warning",
                    "message": (
                        f"Cluster `{cluster_fqn}` participates in a circular "
                        f"dependency among clusters: {group}"
                    ),
                    "rule": {
                        "rationale": (
                            "Circular identity references between aggregate "
                            "clusters prevent independent decomposition, "
                            "deployment, and event sourcing of the aggregates."
                        ),
                        "fix": (
                            "Break the cycle by replacing one direction of the "
                            "reference with a domain event or a process manager "
                            "that coordinates the two aggregates asynchronously."
                        ),
                    },
                    "suggestion": (
                        "Break the cycle by replacing one direction of the "
                        "reference with a domain event or a process manager "
                        "that coordinates the two aggregates asynchronously."
                    ),
                }
            )

    def _diagnose_infra_imports(self, ir: dict[str, Any]) -> None:
        """INFRA_IMPORT_IN_DOMAIN (opt-in): a domain element's source module
        imports from ``protean.adapters``, coupling the domain layer to a
        concrete adapter.

        Off by default; runs only when ``[lint].check_infra_imports`` is true,
        because it reads and AST-parses source files.

        Scans *every* registered domain element — aggregates, entities, value
        objects, repositories, handlers, domain services, process managers,
        subscribers, and so on — not just aggregate-cluster members, because
        infrastructure coupling is at least as likely in a repository or a
        handler as in an aggregate.
        """
        if not self._domain.config.get("lint", {}).get("check_infra_imports", False):
            return

        INFRA_PREFIX = "protean.adapters"
        # module -> True/False cache of "imports infra", to parse each file once.
        module_flags: dict[str, bool] = {}

        def _module_level_imports(tree: ast.Module) -> list[ast.stmt]:
            """Import statements at the module's top level only.

            Nested imports are deliberately excluded: a ``TYPE_CHECKING`` guard,
            an ``except ImportError`` fallback, or a function-local lazy import
            introduce no runtime coupling — they are the idiomatic ways to
            *avoid* it — so flagging them would be a false positive.
            """
            return [
                node
                for node in tree.body
                if isinstance(node, (ast.Import, ast.ImportFrom))
            ]

        def _import_names(node: ast.AST) -> list[str]:
            """Dotted names an import statement brings the adapter package under.

            ``ast.ImportFrom`` must also contribute the imported alias names so
            ``from protean import adapters`` (module ``protean``, alias
            ``adapters``) is matched, not just ``from protean.adapters import``.
            """
            if isinstance(node, ast.Import):
                return [a.name for a in node.names]
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                return [module] + [
                    f"{module}.{a.name}" if module else a.name for a in node.names
                ]
            # Unreachable: callers only pass ``ast.Import``/``ast.ImportFrom``
            # nodes filtered by ``_module_level_imports``.
            return []  # pragma: no cover

        def _module_imports_infra(module: str) -> bool:
            if module in module_flags:
                return module_flags[module]
            flag = False
            try:
                spec = importlib.util.find_spec(module)
            # Broad by design: ``find_spec`` may import a not-yet-loaded parent
            # package and re-execute its ``__init__``, which can raise anything.
            # Fail open (skip the module) rather than abort the diagnostics pass.
            except Exception:
                spec = None
            origin = getattr(spec, "origin", None) if spec else None
            if origin and origin not in ("built-in", "frozen"):
                try:
                    with open(origin, encoding="utf-8") as fh:
                        tree = ast.parse(fh.read())
                except (OSError, SyntaxError, ValueError):
                    tree = None
                if tree is not None:
                    for node in _module_level_imports(tree):
                        names = _import_names(node)
                        if any(
                            n == INFRA_PREFIX or n.startswith(INFRA_PREFIX + ".")
                            for n in names
                        ):
                            flag = True
                            break
            module_flags[module] = flag
            return flag

        # Iterate every non-internal registered element in a stable (fqn) order
        # so emitted diagnostics are deterministic.
        registry = self._domain._domain_registry
        seen: set[str] = set()
        scanned: list[tuple[str, str, str]] = []  # (fqn, name, module)
        for records in registry._elements.values():
            for record in records.values():
                if record.internal:
                    continue
                element_fqn = fqn(record.cls)
                if element_fqn in seen:
                    continue
                seen.add(element_fqn)
                module = getattr(record.cls, "__module__", None)
                if module:
                    scanned.append((element_fqn, record.cls.__name__, module))

        for element_fqn, name, module in sorted(scanned):
            if _module_imports_infra(module):
                self._diagnostics.append(
                    {
                        "code": "INFRA_IMPORT_IN_DOMAIN",
                        "category": "bounded_context",
                        "element": element_fqn,
                        "level": "warning",
                        "message": (
                            f"Domain element `{name}` "
                            f"(module `{module}`) imports from "
                            f"`protean.adapters`."
                        ),
                        "rule": {
                            "rationale": (
                                "Domain elements must not depend on concrete "
                                "infrastructure adapters; importing from "
                                "`protean.adapters` couples the domain layer "
                                "to a specific adapter and breaks the "
                                "ports-and-adapters boundary."
                            ),
                            "fix": (
                                "Remove the `protean.adapters` import from "
                                "the domain module. Depend on domain-layer "
                                "abstractions and let the adapter be wired "
                                "through the domain's provider configuration "
                                "instead."
                            ),
                        },
                        "suggestion": (
                            "Remove the `protean.adapters` import from the "
                            "domain module. Depend on domain-layer "
                            "abstractions and let the adapter be wired "
                            "through the domain's provider configuration "
                            "instead."
                        ),
                    }
                )

    def _apply_suppressions(self) -> None:
        """Filter collected diagnostics through the two suppression channels.

        Mutates :attr:`_diagnostics` in place. Runs at the tail of
        :meth:`_collect_diagnostics` (after custom rules), *before* the final
        code-only sort in :meth:`build`.

        Two channels, applied in order:

        1. **Per-element ``suppress_checks``** — each element may name codes to
           silence for itself. Resolved from the *registry* (not the IR) so
           events/commands/value-objects, which carry no IR ``options`` block,
           are covered identically to aggregates.
        2. **``[lint].suppressions`` allow-list** — a ``{code: N}`` map that
           grandfathers the first ``N`` findings per code in a deterministic
           ``(code, element, field, message)`` total order, letting a codebase
           adopt a rule without failing on pre-existing violations.
        """
        registry = self._domain._domain_registry

        # 1. FQN -> suppressed codes. ``getattr(..., ()) or ()`` is defensive:
        #    element types whose Root never declared the ``suppress_checks``
        #    option (e.g. UPCASTER) carry no ``suppress_checks`` key on
        #    ``meta_``, so the stage must not assume the option's presence — it
        #    guards a missing *option*, not a missing ``meta_``. A bare string
        #    is normalised to a single-code tuple so ``suppress_checks="CODE"``
        #    is not iterated character-by-character.
        fqn_suppress: dict[str, set[str]] = {}
        for records in registry._elements.values():
            for record in records.values():
                if record.internal:
                    continue
                codes = getattr(record.cls.meta_, "suppress_checks", ()) or ()
                if isinstance(codes, str):
                    codes = (codes,)
                if codes:
                    fqn_suppress[fqn(record.cls)] = set(codes)

        survivors = [
            d
            for d in self._diagnostics
            if d.get("code", "")
            not in fqn_suppress.get(d.get("element", ""), frozenset())
        ]

        # 2. Total order first, then grandfather the first N per code. Ordering
        #    the survivors *before* counting makes "the first N" deterministic
        #    and independent of the order rules happened to run in.
        survivors.sort(
            key=lambda d: (
                d.get("code", ""),
                d.get("element", ""),
                d.get("field", ""),
                d.get("message", ""),
            )
        )

        suppressions: dict[str, int] = self._domain.config.get("lint", {}).get(
            "suppressions", {}
        )
        # Fail fast on a malformed value rather than crashing mid-loop with a
        # bare TypeError/AttributeError (this runs on every IR build path, not
        # just ``protean check``).
        error = validate_lint_suppressions(suppressions)
        if error:
            raise ConfigurationError(error)
        seen: dict[str, int] = {}
        kept: list[dict[str, Any]] = []
        for d in survivors:
            code = d.get("code", "")
            seen[code] = seen.get(code, 0) + 1
            if seen[code] <= suppressions.get(code, 0):
                continue
            kept.append(d)

        self._diagnostics = kept

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
                    rule = {
                        "rationale": (
                            "An event with no registered handler is published "
                            "but never consumed, so a state change goes unobserved."
                        ),
                        "fix": (
                            "Register an event handler, projector, or process "
                            "manager for this event, or mark it `published=True` "
                            "if it is intentionally external."
                        ),
                    }
                    self._diagnostics.append(
                        {
                            "category": "handler_completeness",
                            "code": "UNHANDLED_EVENT",
                            "element": event["fqn"],
                            "level": "warning",
                            "message": f"Event {event['name']} has no registered handler",
                            "rule": rule,
                            "suggestion": rule["fix"],
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
                    rule = {
                        "rationale": (
                            "A command with no handler cannot be processed, so "
                            "the intent it represents can never be fulfilled."
                        ),
                        "fix": (
                            "Add a command handler method for this command, or "
                            "remove the command if it is unused."
                        ),
                    }
                    self._diagnostics.append(
                        {
                            "category": "handler_completeness",
                            "code": "UNUSED_COMMAND",
                            "element": command["fqn"],
                            "level": "warning",
                            "message": f"Command {command['name']} has no registered handler",
                            "rule": rule,
                            "suggestion": rule["fix"],
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
                    rule = {
                        "rationale": (
                            "An event-sourced aggregate rebuilds its state by "
                            "applying events; an event without an @apply handler "
                            "is never folded into state."
                        ),
                        "fix": "Add an @apply method on the aggregate for this event.",
                    }
                    self._diagnostics.append(
                        {
                            "category": "handler_completeness",
                            "code": "ES_EVENT_MISSING_APPLY",
                            "element": event_fqn,
                            "level": "warning",
                            "message": (
                                f"Event {event['name']} has no @apply handler "
                                f"on aggregate {aggregate['name']}"
                            ),
                            "rule": rule,
                            "suggestion": rule["fix"],
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
            rule = {
                "rationale": (
                    "Events marked published are meant to leave the bounded "
                    "context, but with no external broker configured they are "
                    "only dispatched internally."
                ),
                "fix": (
                    "Configure `outbox.external_brokers`, or remove "
                    "`published=True` if the events are internal."
                ),
            }
            self._diagnostics.append(
                {
                    "category": "handler_completeness",
                    "code": "PUBLISHED_NO_EXTERNAL_BROKER",
                    "element": self._domain.name,
                    "level": "warning",
                    "message": (
                        "Domain has published events but no external_brokers "
                        "configured in outbox settings. Published events will "
                        "only be dispatched internally."
                    ),
                    "rule": rule,
                    "suggestion": rule["fix"],
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
                rule = {
                    "rationale": (
                        "An aggregate with no command handler has no write "
                        "path — nothing can change its state."
                    ),
                    "fix": (
                        "Add a command handler for the aggregate, or model it "
                        "as a read-only projection if no writes are expected."
                    ),
                }
                self._diagnostics.append(
                    {
                        "category": "handler_completeness",
                        "code": "AGGREGATE_WITHOUT_COMMAND_HANDLER",
                        "element": aggregate["fqn"],
                        "level": "warning",
                        "message": (
                            f"Aggregate `{aggregate['name']}` has no command handler "
                            f"— no write path exists"
                        ),
                        "rule": rule,
                        "suggestion": rule["fix"],
                    }
                )

    def _diagnose_projection_without_projector(self, ir: dict[str, Any]) -> None:
        """PROJECTION_WITHOUT_PROJECTOR: projection with no projector to populate it."""
        for proj_entry in ir["projections"].values():
            proj = proj_entry["projection"]
            # Projections populated by a subscriber/event handler (the
            # anti-corruption-layer / cross-domain pattern) opt out via
            # @domain.projection(externally_populated=True).
            if proj.get("options", {}).get("externally_populated"):
                continue
            if not proj_entry["projectors"]:
                rule = {
                    "rationale": (
                        "A projection with no projector is never populated, so "
                        "queries against it will always return empty."
                    ),
                    "fix": (
                        "Add a projector for the projection, or set "
                        "`externally_populated=True` if it is filled by a "
                        "subscriber."
                    ),
                }
                self._diagnostics.append(
                    {
                        "category": "handler_completeness",
                        "code": "PROJECTION_WITHOUT_PROJECTOR",
                        "element": proj["fqn"],
                        "level": "warning",
                        "message": (
                            f"Projection `{proj['name']}` has no projector "
                            f"to populate it"
                        ),
                        "rule": rule,
                        "suggestion": rule["fix"],
                    }
                )

    def _diagnose_upcaster_gap(self, ir: dict[str, Any]) -> None:
        """UPCASTER_GAP: an event at version N>1 whose stored predecessors have
        no upcaster path to N (build-time signal for a read-time failure).

        Reads the registry rather than ``ir`` because upcaster metadata and an
        event's ``abstract`` flag are not projected into the IR. A malformed
        chain (duplicate/cyclic/non-convergent) is already an error that preempts
        IR building, so this only reaches the two silent cases — no upcasters at
        all, or partial coverage of ``1..N-1``.

        TODO(3.4.6): consume projected upcaster IR once the event catalog adds it.
        """
        registry = self._domain._domain_registry

        # (from_version, to_version) edges per event, keyed by bare name so a
        # string event_type resolves the same way build_chains does. Two events
        # sharing a class name across aggregates would pool edges — a
        # pre-existing limitation of the name-based type string; TODO(3.4.6):
        # key by the qualified type string once upcasters are projected to IR.
        edges_by_event: dict[str, list[tuple[int, int]]] = {}
        for upcaster_cls in self._domain._upcasters:
            name = upcaster_event_name(upcaster_cls.meta_.event_type)
            edges_by_event.setdefault(name, []).append(
                (upcaster_cls.meta_.from_version, upcaster_cls.meta_.to_version)
            )

        for record in registry._elements.get("EVENT", {}).values():
            if record.internal or record.auto_generated:
                continue
            event_cls = record.cls
            if getattr(event_cls.meta_, "abstract", False):
                continue
            current_version = getattr(event_cls, "__version__", 1)
            if current_version <= 1:
                continue

            missing = missing_upcaster_source_versions(
                edges_by_event.get(event_cls.__name__, []), current_version
            )
            if missing:
                versions = ", ".join(f"v{v}" for v in missing)
                rule = {
                    "rationale": (
                        "Stored payloads at older versions with no upcaster "
                        "path to the current version fail to deserialize at "
                        "read time."
                    ),
                    "fix": "Add upcasters covering the missing source versions.",
                }
                self._diagnostics.append(
                    {
                        "category": "versioning",
                        "code": "UPCASTER_GAP",
                        "element": fqn(event_cls),
                        "level": "warning",
                        "message": (
                            f"Event `{event_cls.__name__}` is at version "
                            f"{current_version}; stored payloads at {versions}, if "
                            f"any exist, have no upcaster path to "
                            f"v{current_version} and would fail to deserialize. "
                            f"Add upcasters covering the missing versions."
                        ),
                        "rule": rule,
                        "suggestion": rule["fix"],
                    }
                )

    def _abstract_aggregate_fqns(self) -> set[str]:
        """FQNs of registered aggregates flagged ``abstract`` in their metadata.

        ``abstract`` is not projected into the aggregate IR ``options`` block, so
        the registry is the source of truth (mirroring
        ``_diagnose_aggregate_no_invariants``). Abstract aggregates still get
        clusters (``_build_clusters`` skips only ``record.internal``), so the
        cluster-walking design rules must filter them out here to avoid flagging
        a shape that only exists on a non-instantiable base.
        """
        registry = self._domain._domain_registry
        return {
            fqn(record.cls)
            for record in registry._elements.get("AGGREGATE", {}).values()
            if getattr(record.cls.meta_, "abstract", False)
        }

    def _diagnose_cross_aggregate_reference(self, ir: dict[str, Any]) -> None:
        """CROSS_AGGREGATE_REFERENCE: a ``Reference`` field pointing at a
        *different* aggregate's root (Vernon's Rule 3).

        The compliant, dominant shape is a child entity pointing back at its own
        aggregate root, where ``target`` equals the enclosing cluster key; that
        case must never be flagged. Only ``kind == "reference"`` fields are
        evaluated — ``has_one``/``has_many`` associations are out of scope.
        Framework-injected back-references (``auto_generated``) are skipped, as
        are abstract aggregates.
        """
        cluster_keys = set(ir["clusters"])
        abstract_fqns = self._abstract_aggregate_fqns()
        rule = {
            "rationale": (
                "Aggregates coordinate other aggregates by identity, not by "
                "object reference (Vernon's Rule 3). A `Reference` to another "
                "aggregate's root couples the two into one object graph and "
                "invites a single transaction to span both clusters. The "
                "compliant reference is a child entity pointing back at its own "
                "aggregate root, where the target is the element's own cluster."
            ),
            "fix": (
                "Hold the other aggregate by its identifier instead of a "
                "`Reference`. Replace `Reference(<Other>)` with an `Identifier` "
                "field (for example `<other>_id: Identifier()`) and load the "
                "other aggregate through its own repository when needed."
            ),
        }
        for own, cluster in ir["clusters"].items():
            # Skip infrastructure and abstract aggregates
            if cluster["aggregate"]["fqn"].startswith("protean.adapters."):
                continue
            if cluster["aggregate"]["fqn"] in abstract_fqns:
                continue
            # The root and every child entity belong to *this* cluster, so the
            # "own cluster" of any field found here is the current cluster key.
            owners = [(cluster["aggregate"]["fqn"], cluster["aggregate"]["fields"])]
            owners.extend(
                (entity["fqn"], entity["fields"])
                for entity in cluster["entities"].values()
            )
            for element_fqn, fields in owners:
                for field_name, field in fields.items():
                    if field.get("kind") != "reference":
                        continue
                    if field.get("auto_generated"):
                        continue
                    target = field.get("target")
                    if target in cluster_keys and target != own:
                        self._diagnostics.append(
                            {
                                "category": "aggregate_design",
                                "code": "CROSS_AGGREGATE_REFERENCE",
                                "element": element_fqn,
                                "field": field_name,
                                "level": "warning",
                                "message": (
                                    f"Reference `{field_name}` points at a "
                                    f"different aggregate's root `{target}`; "
                                    f"aggregates should reference each other by "
                                    f"identity, not by `Reference`."
                                ),
                                "rule": rule,
                                "suggestion": rule["fix"],
                            }
                        )

    def _diagnose_es_aggregate_no_events(self, ir: dict[str, Any]) -> None:
        """ES_AGGREGATE_NO_EVENTS: an ``event_sourced=True`` aggregate with no
        *domain* events. It has no state history and cannot be rebuilt by replay.

        Framework-generated events (the ``fact_events`` snapshot, which carries
        ``auto_generated``) do not count: a fact-event snapshot cannot
        reconstitute an event-sourced aggregate by replay. Abstract aggregates
        are skipped.
        """
        abstract_fqns = self._abstract_aggregate_fqns()
        rule = {
            "rationale": (
                "An event-sourced aggregate reconstitutes its state by replaying "
                "its events. With no events registered it can record no state "
                "changes and cannot be rebuilt from its stream."
            ),
            "fix": (
                "Declare at least one domain event with `part_of=<Aggregate>` and "
                "raise it from the aggregate's behaviour, or drop "
                "`event_sourced=True` if the aggregate is not meant to be "
                "event-sourced."
            ),
        }
        for cluster in ir["clusters"].values():
            aggregate = cluster["aggregate"]
            # Skip infrastructure and abstract aggregates
            if aggregate["fqn"].startswith("protean.adapters."):
                continue
            if aggregate["fqn"] in abstract_fqns:
                continue
            if not aggregate["options"].get("is_event_sourced"):
                continue
            domain_events = [
                event
                for event in cluster["events"].values()
                if not event.get("auto_generated", False)
            ]
            if len(domain_events) == 0:
                self._diagnostics.append(
                    {
                        "category": "aggregate_design",
                        "code": "ES_AGGREGATE_NO_EVENTS",
                        "element": aggregate["fqn"],
                        "level": "warning",
                        "message": (
                            f"Event-sourced aggregate `{aggregate['name']}` has "
                            f"no events; it records no state changes and cannot "
                            f"be rebuilt from its stream."
                        ),
                        "rule": rule,
                        "suggestion": rule["fix"],
                    }
                )

    def _diagnose_query_handler_without_query(self, ir: dict[str, Any]) -> None:
        """QUERY_HANDLER_WITHOUT_QUERY: projection with query handlers but no queries.

        A projection wiring a query handler but declaring no ``Query`` has a
        read path that nothing can invoke — the projection registers no query
        for the handler to serve.
        """
        for proj in ir["projections"].values():
            if len(proj["query_handlers"]) > 0 and len(proj["queries"]) == 0:
                projection = proj["projection"]
                rule = {
                    "rationale": (
                        "A projection with a query handler but no query has a "
                        "read path that nothing can invoke — no query is "
                        "registered for the handler to serve."
                    ),
                    "fix": (
                        "Register a `Query(part_of=<projection>)` for the "
                        "handler to serve, or remove the query handler if the "
                        "projection needs no read path."
                    ),
                }
                self._diagnostics.append(
                    {
                        "category": "handler_completeness",
                        "code": "QUERY_HANDLER_WITHOUT_QUERY",
                        "element": projection["fqn"],
                        "level": "warning",
                        "message": (
                            f"Projection `{projection['name']}` has a query "
                            f"handler but no query to serve"
                        ),
                        "rule": rule,
                        "suggestion": rule["fix"],
                    }
                )

    def _diagnose_value_object_mutable_field(self, ir: dict[str, Any]) -> None:
        """VALUE_OBJECT_MUTABLE_FIELD: a value object with a ``list``/``dict``
        field, which gives it mutable state and breaks equality-by-value.

        Only value objects reachable from a (non-abstract) aggregate cluster are
        checked — a VO is embedded in an aggregate/entity or carries ``part_of``.
        Emits one finding per offending field, naming it in the optional
        ``field`` key (mirroring ``DEPRECATED_FIELD``).
        """
        abstract_fqns = self._abstract_aggregate_fqns()
        rule = {
            "rationale": (
                "Value objects are compared by value and must be immutable. A "
                "`List` or `Dict` field gives the value object mutable internal "
                "state, so two instances that should be equal can diverge and "
                "value equality no longer holds."
            ),
            "fix": (
                "Replace the mutable collection with an immutable representation, "
                "or move the collection onto the containing entity or aggregate. "
                "If the values form a concept with its own identity, model them "
                "as an entity referenced by the aggregate instead."
            ),
        }
        for cluster in ir["clusters"].values():
            if cluster["aggregate"]["fqn"] in abstract_fqns:
                continue
            for vo in cluster["value_objects"].values():
                for field_name, field in vo["fields"].items():
                    if field.get("kind") not in ("list", "dict"):
                        continue
                    self._diagnostics.append(
                        {
                            "category": "aggregate_design",
                            "code": "VALUE_OBJECT_MUTABLE_FIELD",
                            "element": vo["fqn"],
                            "field": field_name,
                            "level": "warning",
                            "message": (
                                f"Value object `{vo['name']}` has mutable field "
                                f"`{field_name}` (`{field['kind']}`); value "
                                f"objects must be immutable."
                            ),
                            "rule": rule,
                            "suggestion": rule["fix"],
                        }
                    )

    def _diagnose_projector_handles_orphaned_event(self, ir: dict[str, Any]) -> None:
        """PROJECTOR_HANDLES_ORPHANED_EVENT: projector handling an unregistered event.

        A projector whose handler map keys on an event ``__type__`` that the
        domain does not register is wired to an event that can never be
        dispatched — typically a stale reference after the event was renamed or
        removed. The registered-type set spans *every* registered event, since a
        projector legitimately handles events owned by other aggregates — and
        includes events on ``internal`` aggregates (which are excluded from
        clusters but are still registered and dispatchable).
        """
        registry = self._domain._domain_registry
        registered = {
            getattr(record.cls, "__type__", "")
            for record in registry._elements.get("EVENT", {}).values()
        }
        for proj in ir["projections"].values():
            for projector in proj["projectors"].values():
                for event_type in projector.get("handlers", {}):
                    if event_type not in registered:
                        rule = {
                            "rationale": (
                                "A projector handling an event the domain does "
                                "not register is wired to a type that can never "
                                "be dispatched — usually a stale reference after "
                                "a rename or removal."
                            ),
                            "fix": (
                                "Register the event, or remove the handler for "
                                "the orphaned type from the projector."
                            ),
                        }
                        self._diagnostics.append(
                            {
                                "category": "handler_completeness",
                                "code": "PROJECTOR_HANDLES_ORPHANED_EVENT",
                                "element": projector["fqn"],
                                "level": "warning",
                                "message": (
                                    f"Projector `{projector['name']}` handles "
                                    f"event `{event_type}` which the domain does "
                                    f"not register"
                                ),
                                "rule": rule,
                                "suggestion": rule["fix"],
                            }
                        )

    def _diagnose_command_handler_cross_cluster(self, ir: dict[str, Any]) -> None:
        """COMMAND_HANDLER_CROSS_CLUSTER: handler processing another cluster's command.

        A command handler in cluster A that handles a command owned by cluster
        B crosses an aggregate boundary — the write path for B's command lives
        outside B's cluster. Commands registered in *no* cluster are out of
        scope (they cannot be attributed to an owner), and same-cluster commands
        are the expected case. Only commands are considered — event handlers may
        legitimately react across clusters (the #824 boundary).
        """
        cmd_type_to_cluster = {
            command["__type__"]: agg_fqn
            for agg_fqn, cluster in ir["clusters"].items()
            for command in cluster["commands"].values()
        }
        for agg_fqn, cluster in ir["clusters"].items():
            for ch in cluster["command_handlers"].values():
                for command_type in ch.get("handlers", {}):
                    owner = cmd_type_to_cluster.get(command_type)
                    if owner is not None and owner != agg_fqn:
                        rule = {
                            "rationale": (
                                "A command handler that processes another "
                                "cluster's command puts that aggregate's write "
                                "path outside its consistency boundary."
                            ),
                            "fix": (
                                "Move the command handler into the owning "
                                "cluster, or model the interaction as an event "
                                "reaction across the boundary."
                            ),
                        }
                        self._diagnostics.append(
                            {
                                "category": "handler_completeness",
                                "code": "COMMAND_HANDLER_CROSS_CLUSTER",
                                "element": ch["fqn"],
                                "level": "warning",
                                "message": (
                                    f"Command handler `{ch['name']}` in cluster "
                                    f"`{agg_fqn}` handles command `{command_type}` "
                                    f"owned by cluster `{owner}`"
                                ),
                                "rule": rule,
                                "suggestion": rule["fix"],
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
                rule = {
                    "rationale": (
                        "A large aggregate is a consistency boundary and "
                        "contention hotspot; oversized clusters are hard to "
                        "keep transactionally consistent."
                    ),
                    "fix": (
                        "Split the aggregate into smaller aggregates, or raise "
                        "`[lint] aggregate_size_limit` if the size is "
                        "intentional."
                    ),
                }
                self._diagnostics.append(
                    {
                        "category": "aggregate_design",
                        "code": "AGGREGATE_TOO_LARGE",
                        "element": aggregate["fqn"],
                        "level": "info",
                        "message": (
                            f"Aggregate `{aggregate['name']}` has {entity_count} "
                            f"entities (limit: {limit})"
                        ),
                        "rule": rule,
                        "suggestion": rule["fix"],
                    }
                )

    def _diagnose_handler_too_broad(self, ir: dict[str, Any]) -> None:
        """HANDLER_TOO_BROAD: handler handling too many message types.

        Configurable via ``[lint] handler_breadth_limit`` in domain config
        (default 5).
        """
        limit = self._domain.config.get("lint", {}).get("handler_breadth_limit", 5)
        rule = {
            "rationale": (
                "A handler that handles many message types accretes unrelated "
                "responsibilities and becomes hard to reason about."
            ),
            "fix": (
                "Split the handler into focused handlers, or raise "
                "`[lint] handler_breadth_limit` if the breadth is intentional."
            ),
        }
        for cluster in ir["clusters"].values():
            # Check command handlers
            for ch in cluster["command_handlers"].values():
                handler_count = len(ch.get("handlers", {}))
                if handler_count > limit:
                    self._diagnostics.append(
                        {
                            "category": "aggregate_design",
                            "code": "HANDLER_TOO_BROAD",
                            "element": ch["fqn"],
                            "level": "info",
                            "message": (
                                f"Handler `{ch['name']}` handles {handler_count} "
                                f"message types (limit: {limit})"
                            ),
                            "rule": rule,
                            "suggestion": rule["fix"],
                        }
                    )
            # Check event handlers
            for eh in cluster["event_handlers"].values():
                handler_count = len(eh.get("handlers", {}))
                if handler_count > limit:
                    self._diagnostics.append(
                        {
                            "category": "aggregate_design",
                            "code": "HANDLER_TOO_BROAD",
                            "element": eh["fqn"],
                            "level": "info",
                            "message": (
                                f"Handler `{eh['name']}` handles {handler_count} "
                                f"message types (limit: {limit})"
                            ),
                            "rule": rule,
                            "suggestion": rule["fix"],
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
                    rule = {
                        "rationale": (
                            "An event with no fields carries no information "
                            "beyond its name, so consumers cannot react to what "
                            "actually changed."
                        ),
                        "fix": (
                            "Add fields capturing the state change, or confirm "
                            "the event is intentionally a bare signal."
                        ),
                    }
                    self._diagnostics.append(
                        {
                            "category": "aggregate_design",
                            "code": "EVENT_WITHOUT_DATA",
                            "element": event["fqn"],
                            "level": "info",
                            "message": (
                                f"Event `{event['name']}` has no user-defined fields"
                            ),
                            "rule": rule,
                            "suggestion": rule["fix"],
                        }
                    )

    def _diagnose_subscriber_no_streams(self, ir: dict[str, Any]) -> None:
        """SUBSCRIBER_NO_STREAMS: subscriber with no stream to consume.

        A subscriber whose ``stream`` is empty or unset has nothing to
        subscribe to, so it will never be invoked.
        """
        for sub in ir["flows"]["subscribers"].values():
            if not sub.get("stream"):
                rule = {
                    "rationale": (
                        "A subscriber with no stream has nothing to consume, so "
                        "it is registered but can never be invoked."
                    ),
                    "fix": (
                        "Set the subscriber's `stream`, or remove the "
                        "subscriber if it is unused."
                    ),
                }
                self._diagnostics.append(
                    {
                        "category": "handler_completeness",
                        "code": "SUBSCRIBER_NO_STREAMS",
                        "element": sub["fqn"],
                        "level": "info",
                        "message": (
                            f"Subscriber `{sub['name']}` declares no stream to consume"
                        ),
                        "rule": rule,
                        "suggestion": rule["fix"],
                    }
                )

    def _diagnose_process_manager_unclosed(self, ir: dict[str, Any]) -> None:
        """PROCESS_MANAGER_UNCLOSED: process manager with no terminating handler.

        A process manager that has handlers but none marked ``end=True`` has no
        explicit completion, so instances accumulate without ever being retired.
        A handler-less process manager is not flagged here — it has no flow to
        close and is a different (empty-definition) smell.
        """
        for pm in ir["flows"]["process_managers"].values():
            handlers = pm["handlers"]
            if handlers and not any(h.get("end") for h in handlers.values()):
                rule = {
                    "rationale": (
                        "A process manager with no `end=True` handler never "
                        "signals completion, so its instances accumulate "
                        "without being retired."
                    ),
                    "fix": (
                        "Mark the terminating handler with `end=True` so the "
                        "process manager closes its instances."
                    ),
                }
                self._diagnostics.append(
                    {
                        "category": "handler_completeness",
                        "code": "PROCESS_MANAGER_UNCLOSED",
                        "element": pm["fqn"],
                        "level": "info",
                        "message": (
                            f"Process manager `{pm['name']}` has no handler "
                            f"marked `end=True` to close its instances"
                        ),
                        "rule": rule,
                        "suggestion": rule["fix"],
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

            superseded_by = element.get("superseded_by")
            if superseded_by:
                msg += f"; superseded by `{superseded_by}`"

            rule = {
                "rationale": (
                    "A deprecated element is scheduled for removal; code "
                    "depending on it will break at the removal version."
                ),
                "fix": (
                    "Migrate to the replacement element before the scheduled "
                    "removal version."
                ),
            }
            self._diagnostics.append(
                {
                    "category": "deprecation",
                    "code": "DEPRECATED_ELEMENT",
                    "element": fqn_val,
                    "level": "info",
                    "message": msg,
                    "rule": rule,
                    "suggestion": rule["fix"],
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
                        f"Field `{name}.{field_name}` is deprecated since v{f_since}"
                    )
                f_rule = {
                    "rationale": (
                        "A deprecated field is scheduled for removal; code "
                        "reading or writing it will break at the removal version."
                    ),
                    "fix": (
                        "Migrate to the replacement field before the scheduled "
                        "removal version."
                    ),
                }
                self._diagnostics.append(
                    {
                        "category": "deprecation",
                        "code": "DEPRECATED_FIELD",
                        "element": fqn_val,
                        "field": field_name,
                        "level": "info",
                        "message": f_msg,
                        "rule": f_rule,
                        "suggestion": f_rule["fix"],
                    }
                )

        # Option-level deprecation (currently only commands passed the event-only
        # ``published`` option). Warning-level: unlike a still-functional
        # deprecated element, the option is inert today and becomes a hard
        # ``IncorrectUsageError`` at v1.0.0.
        for opt in element.get("deprecated_options", []):
            opt_rule = {
                "rationale": (
                    "The option is inert today and becomes a hard "
                    "IncorrectUsageError at v1.0.0."
                ),
                "fix": (f"Remove the `{opt}` option from `{name}`; it has no effect."),
            }
            self._diagnostics.append(
                {
                    "category": "deprecation",
                    "code": "DEPRECATED_OPTION",
                    "element": fqn_val,
                    "level": "warning",
                    "message": (
                        f"The `{opt}` option on `{name}` is deprecated and "
                        f"scheduled for removal in v1.0.0; commands are internal "
                        f"to the bounded context and carry no published-language "
                        f"or fact-event semantics, so it has no effect."
                    ),
                    "rule": opt_rule,
                    "suggestion": opt_rule["fix"],
                }
            )

    def _diagnose_deprecated_options(self, ir: dict[str, Any]) -> None:
        """DEPRECATED_OPTION: a deprecated decorator/register option was used.

        Reads the aggregate registry (the deprecated-option marker is not
        projected into the IR, keeping the IR wire format unchanged) and emits
        an INFO-level diagnostic per aggregate that used a deprecated option
        alias, e.g. ``is_event_sourced=`` instead of ``event_sourced=``.
        """
        registry = self._domain._domain_registry
        for record in registry._elements.get("AGGREGATE", {}).values():
            # Read the class's own attribute (not an inherited one) so a
            # subclass of an alias-using aggregate is not wrongly flagged.
            used = record.cls.__dict__.get("_deprecated_options_used", ())
            for option in used:
                rule = {
                    "rationale": (
                        "The option is a deprecated alias scheduled for removal."
                    ),
                    "fix": "Use `event_sourced` instead of the deprecated alias.",
                }
                self._diagnostics.append(
                    {
                        "category": "deprecation",
                        "code": "DEPRECATED_OPTION",
                        "element": fqn(record.cls),
                        "level": "info",
                        "message": (
                            f"Option `{option}` is deprecated; "
                            f"use `event_sourced` instead."
                        ),
                        "rule": rule,
                        "suggestion": rule["fix"],
                    }
                )

    def _diagnose_email_deprecated(self, ir: dict[str, Any]) -> None:
        """DEPRECATED_EMAIL: registered ``@domain.email`` elements.

        The email subsystem is deprecated (epic #1102, removed at v1.0.0).
        Email elements are not projected into the IR (they appear in no
        cluster/projection/flow), so ``_diagnose_deprecated_elements`` cannot
        see them. Read the registry directly, mirroring
        ``_diagnose_upcaster_gap``, and emit one INFO-level diagnostic per
        registered email element (INFO keeps ``check``'s exit code at 0 for a
        deprecation, matching the ``DEPRECATED_ELEMENT`` convention).
        """
        registry = self._domain._domain_registry
        for record in registry._elements.get("EMAIL", {}).values():
            if record.internal or record.auto_generated:
                continue
            email_cls = record.cls
            rule = {
                "rationale": (
                    "The email subsystem is deprecated and scheduled for "
                    "removal in v1.0.0."
                ),
                "fix": (
                    "Notify from an event handler or subscriber that calls an "
                    "application-level notification service instead."
                ),
            }
            self._diagnostics.append(
                {
                    "category": "deprecation",
                    "code": "DEPRECATED_EMAIL",
                    "element": fqn(email_cls),
                    "level": "info",
                    "message": (
                        f"Email element `{email_cls.__name__}` uses the "
                        f"deprecated email subsystem, scheduled for removal in "
                        f"v1.0.0. Notify from an event handler or subscriber "
                        f"that calls an application-level notification service "
                        f"instead."
                    ),
                    "rule": rule,
                    "suggestion": rule["fix"],
                }
            )

    def _diagnose_aggregate_no_invariants(self, ir: dict[str, Any]) -> None:
        """AGGREGATE_NO_INVARIANTS: an aggregate with no pre/post invariants,
        usually an anemic data holder rather than a true consistency boundary.
        INFO-level design nudge, not a build failure.

        ``abstract`` is not projected into the aggregate IR ``options`` block, so
        it is sourced from the registry (mirroring ``_diagnose_upcaster_gap`` /
        ``_diagnose_email_deprecated``). Internal and abstract aggregates are
        skipped. ``invariants`` is the dict ``{"pre": [...], "post": [...]}``;
        flag only when *both* lists are empty.
        """
        registry = self._domain._domain_registry
        rule = {
            "rationale": (
                "An aggregate is a consistency boundary. With no pre- or "
                "post-invariants it enforces no business rules and is usually an "
                "anemic data holder rather than a true aggregate."
            ),
            "fix": (
                "Add one or more `@invariant.pre` or `@invariant.post` methods "
                "expressing the business rules the aggregate must always satisfy, "
                "or reconsider whether this concept is an aggregate at all."
            ),
        }
        for record in registry._elements.get("AGGREGATE", {}).values():
            if record.internal:
                continue
            if getattr(record.cls.meta_, "abstract", False):
                continue
            agg_fqn = fqn(record.cls)
            cluster = ir["clusters"].get(agg_fqn)
            if cluster is None:  # pragma: no cover
                # Defensive: ``_build_clusters`` clusters every non-internal
                # aggregate, so a non-internal, non-abstract record always has a
                # cluster. Unreachable given the current builder, kept as a guard.
                continue
            invariants = cluster["aggregate"]["invariants"]
            if not invariants["pre"] and not invariants["post"]:
                self._diagnostics.append(
                    {
                        "category": "aggregate_design",
                        "code": "AGGREGATE_NO_INVARIANTS",
                        "element": agg_fqn,
                        "level": "info",
                        "message": (
                            f"Aggregate `{record.cls.__name__}` has no pre/post "
                            f"invariants (own or inherited); it enforces no "
                            f"business rules and may be an anemic data holder."
                        ),
                        "rule": rule,
                        "suggestion": rule["fix"],
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
                # Custom findings default to the ``custom`` category so they
                # carry the same schema shape as built-in diagnostics; the
                # forward-compat ``rule``/``suggestion`` keys stay optional.
                item.setdefault("category", "custom")
                self._diagnostics.append(item)

    @staticmethod
    def _import_callable(dotted_path: str) -> Any:
        """Import a callable from a dotted path like ``'my_app.lint.check_names'``."""

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
        """SHA-256 of canonical JSON with volatile/version keys removed.

        Excludes :data:`protean.ir.constants.VOLATILE_IR_KEYS` so the checksum
        reflects domain *content* only and stays in lockstep with ``ir diff``.
        """
        ir_copy = {k: v for k, v in ir.items() if k not in VOLATILE_IR_KEYS}
        canonical = json.dumps(ir_copy, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"
