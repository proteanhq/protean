"""IRBuilder — walks a Domain composite root and produces an IR dict.

Usage::

    from protean.ir.builder import IRBuilder

    domain.init()
    ir = IRBuilder(domain).build()
"""

from __future__ import annotations

import ast
import datetime as _dt
import decimal
import hashlib
import importlib
import json
import logging
import types as _types
import typing
from collections.abc import Callable, Iterator
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from protean._deprecation import DEPRECATIONS
from protean.core.aggregate import BaseAggregate
from protean.core.index import Index, RawIndex
from protean.core.value_object import BaseValueObject
from protean.exceptions import ConfigurationError
from protean.fields.association import HasMany, HasOne, Reference
from protean.fields.basic import ValueObjectList
from protean.fields.embedded import ValueObject
from protean.fields.resolved import ResolvedField
from protean.fields.spec import _UNSET
from protean.ir import SCHEMA_URL, SCHEMA_VERSION
from protean.ir.analysis import (
    RAISE_METHOD,
    BehavioralView,
    ElementIndex,
    ReceiverRole,
    SourceProvider,
)
from protean.ir.constants import (
    VOLATILE_IR_KEYS,
    is_external_io_call,
    is_persistence_call,
)
from protean.ir.diagnostics import Diagnostic, DiagnosticCode, build_diagnostic
from protean.utils import (
    _DEPRECATED_PLUMBING,
    DomainObjects,
    _callable_qualname,
    fqn,
)
from protean.utils.container import Element, OptionsMixin
from protean.utils.reflection import _ID_FIELD_NAME, declared_fields
from protean.utils.upcasting import (
    missing_upcaster_source_versions,
    upcaster_event_name,
)

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.ir.analysis import SourceLocation

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


# Naming-convention fitness functions (info-level advisory diagnostics).
#
# Imperative verbs a well-named command is expected to begin with. The check is
# case-insensitive: the (lowercased) command name is compared against these
# prefixes, so every entry is stored lowercase. This is a closed, pinned
# heuristic floor — not an exhaustive lexicon — so teams whose ubiquitous
# language uses verbs outside this set can add them through
# ``[lint].command_verbs``, or silence a single finding via ``suppress_checks``.
IMPERATIVE_VERBS = {
    "accept",
    "activate",
    "add",
    "apply",
    "approve",
    "archive",
    "assign",
    "book",
    "cancel",
    "change",
    "charge",
    "close",
    "complete",
    "confirm",
    "convert",
    "create",
    "credit",
    "deactivate",
    "debit",
    "decline",
    "delete",
    "deliver",
    "deposit",
    "disable",
    "dispatch",
    "enable",
    "enroll",
    "escalate",
    "fail",
    "freeze",
    "generate",
    "grant",
    "hire",
    "initiate",
    "invite",
    "make",
    "mark",
    "merge",
    "notify",
    "onboard",
    "open",
    "pay",
    "place",
    "process",
    "publish",
    "reactivate",
    "record",
    "reduce",
    "refund",
    "register",
    "reject",
    "release",
    "remove",
    "rename",
    "renew",
    "reopen",
    "request",
    "reserve",
    "reset",
    "restock",
    "restore",
    "resume",
    "revoke",
    "schedule",
    "send",
    "set",
    "ship",
    "split",
    "start",
    "stop",
    "submit",
    "suspend",
    "transfer",
    "unassign",
    "update",
    "validate",
    "verify",
    "withdraw",
}

# Suffixes that signal an aggregate is named as a verb, gerund, or adjective
# rather than a domain-concept noun. Agent-noun suffixes (``-er``/``-or``/
# ``-ator``) are deliberately excluded so ``Customer``, ``Supplier``,
# ``Vendor``, and ``Auditor`` pass without an allow-list. Matched
# case-insensitively against a lowercased name, with a length guard so a name
# equal to a suffix never self-matches.
NON_NOUN_AGGREGATE_SUFFIXES = (
    "ing",  # gerund / present participle: Processing, Shipping
    "ify",  # verb infinitive:            Notify, Classify
    "ize",  # verb infinitive (US):       Serialize, Authorize
    "ise",  # verb infinitive (UK):       Serialise, Authorise
    "ive",  # adjective:                  Recursive, Directive
    "ous",  # adjective:                  Continuous, Ambiguous
    "able",  # adjective:                  Cancelable, Schedulable
    "ible",  # adjective:                  Convertible, Divisible
    "ful",  # adjective:                  Delightful, Successful
)

# Repository-query method names whose keyword fields name a filter path the
# UNINDEXED_FILTER_PATH rule evaluates. These are the read/lookup surfaces of the
# ``QuerySet``/repository API (``facts._QUERY_METHODS`` minus ``add``, which
# persists rather than queries): each names the field(s) a query filters on, so a
# call to one on a recognized repository receiver is a filter path to check
# against the target aggregate's declared indexes.
FILTER_PATH_QUERY_METHODS = frozenset({"filter", "get", "find", "find_by", "exclude"})

# Field ``kind`` values that map to no single scalar column named for the
# field, so a filter on the field *name* cannot be served by an ``Index`` on
# that name: embedded value objects (which expand into several columns, none
# named for the field), ``has_one``/``has_many`` associations (which live on
# the other side of the relationship, with no column here at all), and
# ``reference`` (which *does* persist a single FK column, but under the
# differently-named shadow attribute ``Reference.get_attribute_name()``
# produces — e.g. ``vendor`` persists as ``vendor_id`` — never under the
# ``reference`` field's own declared name; a declared ``Index("vendor")``
# resolves through that same shadow-attribute map, so it covers a filter on
# the declared name identically). The rule evaluates only scalar fields, the
# same scalar-field scope the sibling ``UNBOUNDED_INDEXED_STRING`` rule keeps.
NON_SCALAR_FILTER_FIELD_KINDS = frozenset(
    {"value_object", "value_object_list", "has_one", "has_many", "reference"}
)


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
    """Return an error message if ``[lint]`` or one of its options is malformed.

    Returns ``None`` when ``[lint]`` is a table, ``rules`` is a list of strings,
    ``command_verbs`` is a list of non-empty words made of ASCII letters,
    ``aggregate_size_limit`` and ``handler_breadth_limit`` are non-negative
    integers, and ``check_infra_imports`` and ``check_adapter_calls`` are
    booleans. ``level`` and ``suppressions`` are checked elsewhere.

    Call this before reading any ``[lint]`` key. The reads go through
    ``domain.config.get("lint", {}).get(...)``, which raises a bare
    ``AttributeError`` when ``[lint]`` is not a table.
    """
    if not isinstance(lint_config, dict):
        return f"[lint] must be a table, got {type(lint_config).__name__}."

    rules = lint_config.get("rules", [])
    if not isinstance(rules, list) or not all(isinstance(r, str) for r in rules):
        return f"[lint].rules must be a list of dotted paths, got {rules!r}."

    command_verbs = lint_config.get("command_verbs", [])
    # ASCII only: the name check compares the lowercased verb against the
    # command name by index, and some non-ASCII letters change length when
    # lowercased.
    if not isinstance(command_verbs, list) or not all(
        isinstance(v, str) and v.isascii() and v.isalpha() for v in command_verbs
    ):
        return (
            "[lint].command_verbs must be a list of non-empty words of ASCII "
            "letters, "
            f"got {command_verbs!r}."
        )

    for key in ("aggregate_size_limit", "handler_breadth_limit"):
        limit = lint_config.get(key, 5)
        # ``bool`` is an ``int`` subclass, so ``true`` would read as ``1``.
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            return f"[lint].{key} must be a non-negative integer, got {limit!r}."

    for key in ("check_infra_imports", "check_adapter_calls"):
        flag = lint_config.get(key, False)
        if not isinstance(flag, bool):
            return f"[lint].{key} must be true or false, got {flag!r}."

    return None


def _is_value_object_class(candidate: Any) -> bool:
    return isinstance(candidate, type) and issubclass(candidate, BaseValueObject)


_ADAPTERS_PACKAGE = "protean.adapters"


def _is_adapters_name(name: str) -> bool:
    """Return whether a dotted name is ``protean.adapters`` or lies under it."""
    return name == _ADAPTERS_PACKAGE or name.startswith(_ADAPTERS_PACKAGE + ".")


class _TarjanSCC:
    """Tarjan's strongly-connected-components algorithm over one graph.

    Iterative, with an explicit work stack of ``[node, next-neighbour-index]``
    frames, so a deep graph cannot hit the recursion limit.
    """

    def __init__(self, adjacency: dict[str, list[str]]) -> None:
        self._adjacency = adjacency
        self._index_of: dict[str, int] = {}
        self._lowlink: dict[str, int] = {}
        self._on_stack: dict[str, bool] = {}
        self._stack: list[str] = []
        self._found: list[list[str]] = []
        self._counter = 0

    def _components(self) -> list[list[str]]:
        """Return each component as a sorted member list, the list itself sorted."""
        for start in sorted(self._adjacency):
            if start not in self._index_of:
                self._explore(start)
        return sorted(self._found)

    def _explore(self, start: str) -> None:
        """Visit every node reachable from ``start`` that is not yet indexed."""
        work: list[list[Any]] = [[start, 0]]
        while work:
            node, i = work[-1]
            if i == 0:
                self._enter(node)
            if self._descend(work, node, i):
                continue
            # Node fully explored: close a component if it is a root.
            self._close_if_root(node)
            work.pop()
            if work:  # propagate lowlink up to the parent frame
                parent = work[-1][0]
                self._lowlink[parent] = min(self._lowlink[parent], self._lowlink[node])

    def _enter(self, node: str) -> None:
        """Index ``node`` and push it on the Tarjan stack."""
        self._index_of[node] = self._lowlink[node] = self._counter
        self._counter += 1
        self._stack.append(node)
        self._on_stack[node] = True

    def _descend(self, work: list[list[Any]], node: str, i: int) -> bool:
        """Scan ``node``'s neighbours from index ``i``.

        Returns ``True`` after pushing a frame for the first unvisited
        neighbour, and ``False`` once every neighbour has been scanned.
        """
        neighbours = self._adjacency[node]
        while i < len(neighbours):
            nxt = neighbours[i]
            i += 1
            if nxt not in self._index_of:
                work[-1][1] = i  # resume after this neighbour
                work.append([nxt, 0])
                return True
            if self._on_stack.get(nxt):
                self._lowlink[node] = min(self._lowlink[node], self._index_of[nxt])
        return False

    def _close_if_root(self, node: str) -> None:
        """Pop ``node``'s component off the stack when ``node`` is its root."""
        if self._lowlink[node] != self._index_of[node]:
            return
        component: list[str] = []
        while True:
            w = self._stack.pop()
            self._on_stack[w] = False
            component.append(w)
            if w == node:
                break
        self._found.append(sorted(component))


_FIELD_MODULES = frozenset({"protean.fields", "protean.fields.basic"})
_DEPRECATED_FIELDS = frozenset({"Method", "Nested"})


class _DeprecatedImportScan:
    """The deprecated import surfaces one parsed module uses.

    :meth:`IRBuilder._find_deprecated_import_uses` states which surfaces count.
    """

    def __init__(self, tree: ast.Module) -> None:
        self._tree = tree
        self._plumbing = set(_DEPRECATED_PLUMBING)
        self._module_aliases = self._whole_module_aliases(tree)
        self._field_aliases = self._field_import_aliases(tree)
        self._found: set[tuple[str, str]] = set()

    @staticmethod
    def _whole_module_aliases(tree: ast.Module) -> dict[str, str]:
        """Return alias -> module for each ``import <module> as <alias>``."""
        # Whole-module import aliases: `import protean.fields as pf` binds
        # `pf` -> `protean.fields`.
        module_aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        module_aliases[alias.asname] = alias.name
        return module_aliases

    @staticmethod
    def _field_import_aliases(tree: ast.Module) -> dict[str, str]:
        """Return local name -> canonical name of module-level Method/Nested imports."""
        # Module-level names bound to Method/Nested from either field module.
        field_aliases: dict[str, str] = {}  # local name -> canonical
        for stmt in tree.body:
            if isinstance(stmt, ast.ImportFrom) and stmt.module in _FIELD_MODULES:
                for alias in stmt.names:
                    if alias.name in _DEPRECATED_FIELDS:
                        field_aliases[alias.asname or alias.name] = alias.name
        return field_aliases

    def _dotted(self, node: ast.AST) -> str | None:
        """Dotted name of an attribute/name chain, or ``None`` if impure."""
        if isinstance(node, ast.Name):
            return self._module_aliases.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            base = self._dotted(node.value)
            return f"{base}.{node.attr}" if base is not None else None
        return None

    def _uses(self) -> list[tuple[str, str]]:
        """Return the sorted ``(kind, symbol)`` pairs found in the tree."""
        for node in ast.walk(self._tree):
            # ``from protean.utils import <plumbing-name>`` — the import itself
            # is the deprecated access (it fires ``__getattr__`` at runtime).
            if isinstance(node, ast.ImportFrom) and node.module == "protean.utils":
                self._visit_utils_import(node)
            # ``protean.utils.<plumbing-name>`` attribute access.
            elif isinstance(node, ast.Attribute) and node.attr in self._plumbing:
                if self._dotted(node.value) == "protean.utils":
                    self._found.add(("util", f"protean.utils.{node.attr}"))
            # ``Method(...)`` / ``Nested(...)`` call bound to a module import, or
            # a ``protean.fields.Method(...)`` or ``protean.fields.basic.Method(...)``
            # attribute call.
            elif isinstance(node, ast.Call):
                self._visit_call(node)
        return sorted(self._found)

    def _visit_utils_import(self, node: ast.ImportFrom) -> None:
        """Record each plumbing name a ``from protean.utils import`` names."""
        for alias in node.names:
            if alias.name in self._plumbing:
                self._found.add(("util", f"protean.utils.{alias.name}"))

    def _visit_call(self, node: ast.Call) -> None:
        """Record a ``Method``/``Nested`` call reached through a field module."""
        func = node.func
        if isinstance(func, ast.Name) and func.id in self._field_aliases:
            self._found.add(("field", self._field_aliases[func.id]))
        elif isinstance(func, ast.Attribute) and func.attr in _DEPRECATED_FIELDS:
            base = self._dotted(func.value)
            if base in _FIELD_MODULES:
                self._found.add(("field", func.attr))


class _ClusterSurfaces:
    """The name surfaces of a build's clusters, computed once per cluster.

    A cluster's surface maps a method name to the ``(element_fqn, method_name)``
    pairs that define it across the aggregate and its entities. It holds
    body-only methods (via ``element_methods``), so inherited framework methods
    (``raise_``/``add``/``get``) are not in the surface. Every section key
    resolves through ``fqn_to_cls`` by construction: a cluster/flow/projection
    key is the ``fqn`` of a registered element, and ``fqn_to_cls`` is keyed by
    that same ``fqn``, so the lookups index directly (fail-open lives one layer
    down, in ``element_facts``).
    """

    def __init__(
        self,
        view: BehavioralView,
        clusters: dict[str, Any],
        fqn_to_cls: dict[str, type],
    ) -> None:
        self._view = view
        self._clusters = clusters
        self._fqn_to_cls = fqn_to_cls
        self._cache: dict[str, dict[str, list[tuple[str, str]]]] = {}

    def _cluster(self, agg_fqn: str) -> dict[str, list[tuple[str, str]]]:
        """Return the name surface of one aggregate's cluster."""
        cached = self._cache.get(agg_fqn)
        if cached is not None:
            return cached
        surface: dict[str, list[tuple[str, str]]] = {}
        cluster = self._clusters[agg_fqn]
        for elem_fqn in [agg_fqn, *cluster["entities"].keys()]:
            elem_cls = self._fqn_to_cls[elem_fqn]
            for method in self._view.element_methods(elem_cls):
                surface.setdefault(method.name, []).append((elem_fqn, method.name))
        self._cache[agg_fqn] = surface
        return surface

    def _union(self, agg_fqns: set[str]) -> dict[str, list[tuple[str, str]]]:
        """Return the merged name surface of several clusters, in sorted order."""
        merged: dict[str, list[tuple[str, str]]] = {}
        for agg_fqn in sorted(agg_fqns):
            for name, pairs in self._cluster(agg_fqn).items():
                merged.setdefault(name, []).extend(pairs)
        return merged


class IRBuilder:
    """Build the Intermediate Representation for a Protean domain.

    The domain **must** be initialised (``domain.init()``) before calling
    :meth:`build` — the builder reads the fully-wired composite root.
    """

    def __init__(self, domain: Domain) -> None:
        self._domain = domain
        # Built-in diagnostics are the full ``Diagnostic`` shape from
        # ``build_diagnostic``; custom lint rules (``_run_custom_lint_rules``)
        # contribute dicts that only guarantee ``code``/``element``/``level``/
        # ``message``, so the element type reflects both shapes.
        self._diagnostics: list[Diagnostic | dict[str, Any]] = []
        self._source: SourceProvider | None = None
        self._index: ElementIndex | None = None
        self._view: BehavioralView | None = None

    @property
    def source(self) -> SourceProvider:
        """Parsed-source access for the diagnostic rules that need it.

        One provider per builder, so its cache dies with the build and a later
        build in the same process re-reads files that changed in between.
        Created on first use; the real cost (locating, reading and parsing a
        module) is deferred until a rule actually asks for a tree.
        """
        if self._source is None:
            self._source = SourceProvider(self._domain)
        return self._source

    @property
    def index(self) -> ElementIndex:
        """Class/method index over the parsed sources, for behavioral rules.

        One index per builder, sharing this builder's :attr:`source` provider,
        so a module the index has already read is not parsed again for a rule
        that asks the provider for it under the same name. Created on first
        use, and it walks the domain's package only when first queried, so a
        build whose rules never ask for it costs nothing.
        """
        if self._index is None:
            self._index = ElementIndex(self._domain, self.source)
        return self._index

    @property
    def view(self) -> BehavioralView:
        """Queryable behavioral view over the parsed sources, for rules.

        One view per builder, sharing this builder's :attr:`source` provider and
        :attr:`index`, so the modules a rule already read are not parsed again
        for their facts or dataflow. It is the single object a ``_diagnose_*``
        rule asks for method-level facts and flow, the way it reads the IR —
        created on first use, and each layer under it stays lazy, so a build
        whose rules never ask for it costs nothing.
        """
        if self._view is None:
            self._view = BehavioralView(self._domain, self.source, self.index)
        return self._view

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        """Return the complete IR dictionary."""
        ir: dict[str, Any] = {
            "$schema": SCHEMA_URL,
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

        # Sparse for the same reason: enricher-free domains keep their IR.
        enrichers = self._build_enrichers()
        if enrichers:
            ir["enrichers"] = enrichers

        # Materialize raise/invoke edges as a post-pass over the assembled
        # clusters, flows and projections (the per-element extractors do not
        # hold a cluster's whole element set, which ``invokes`` needs).
        self._materialize_method_edges(ir)

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
    def _extract_deprecated(element_cls: type[_ElementCls]) -> dict[str, str] | None:
        """Return the normalized ``deprecated`` metadata from an element's meta_.

        Returns ``None`` when the element is not deprecated (sparse IR).
        """
        return getattr(getattr(element_cls, "meta_", None), "deprecated", None)

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
            entry = self._field_entry(cls, field_obj, field_meta.get(name))
            if entry is None:
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

    def _field_entry(
        self, cls: type[_ElementCls], field_obj: Any, spec: Any | None
    ) -> dict[str, Any] | None:
        """Return the unsorted IR entry of one declared field.

        Returns ``None`` for a field type the IR does not describe.
        """
        if isinstance(field_obj, ValueObject):
            return self._value_object_entry(
                field_obj.value_object_cls, field_obj.required
            )
        if isinstance(field_obj, ValueObjectList):
            return self._value_object_list_entry(field_obj)
        if isinstance(field_obj, (HasOne, HasMany)):
            return self._association_entry(field_obj)
        if isinstance(field_obj, Reference):
            return self._reference_entry(field_obj)
        if isinstance(field_obj, ResolvedField):
            return self._resolved_field_entry(cls, field_obj, spec)
        return None

    def _value_object_list_entry(self, field_obj: ValueObjectList) -> dict[str, Any]:
        """Return the IR entry of a ``ValueObjectList`` field."""
        entry: dict[str, Any] = {"kind": "value_object_list"}
        if isinstance(field_obj.content_type, ValueObject):
            entry["target"] = self._resolved_fqn(
                field_obj.content_type.value_object_cls
            )
        else:
            entry["target"] = fqn(field_obj.content_type)
        return entry

    def _association_entry(self, field_obj: HasOne | HasMany) -> dict[str, Any]:
        """Return the IR entry of a ``HasOne`` or ``HasMany`` field."""
        entry: dict[str, Any] = {
            "kind": "has_one" if isinstance(field_obj, HasOne) else "has_many",
            "target": self._resolved_fqn(field_obj.to_cls),
        }
        if field_obj.via is not None:
            entry["via"] = field_obj.via
        return entry

    def _reference_entry(self, field_obj: Reference) -> dict[str, Any]:
        """Return the IR entry of a ``Reference`` field."""
        entry: dict[str, Any] = {
            "kind": "reference",
            "target": self._resolved_fqn(field_obj.to_cls),
            "linked_attribute": field_obj.linked_attribute,
        }
        if field_obj._auto_generated:
            entry["auto_generated"] = True
        return entry

    def _value_object_entry(self, target: type | str, required: bool) -> dict[str, Any]:
        """Return the IR entry of a field that embeds one value object."""
        entry: dict[str, Any] = {
            "kind": "value_object",
            "target": self._resolved_fqn(target),
        }
        if required:
            entry["required"] = True
        return entry

    def _resolved_field_entry(
        self, cls: Any, field: ResolvedField, spec: Any | None
    ) -> dict[str, Any]:
        """Return the IR entry of a ``ResolvedField`` declared on ``cls``."""
        entry = self._extract_resolved_field(field, spec)
        message_vo = self._message_value_object(cls, field)
        if message_vo is not None:
            # Keep the field's own metadata (default, description, deprecated)
            # and replace only what it says about the field's type.
            entry.pop("type", None)
            entry.update(self._value_object_entry(message_vo, field.required))
        return entry

    def _message_value_object(self, cls: Any, field: ResolvedField) -> type | None:
        """Return the value object class a command or event field holds, if any.

        A command or event turns its ``ValueObject`` fields into plain resolved
        fields typed by the value object class (``Addr`` or ``Addr | None``), the
        same type a bare annotation such as ``addr: Addr`` gives. Fields of any
        other element, list or dict fields, and unions of more than one type
        besides ``None`` (``Addr | str``) return ``None``.
        """
        if getattr(cls, "element_type", None) not in (
            DomainObjects.COMMAND,
            DomainObjects.EVENT,
        ):
            return None
        return self._single_value_object(field._python_type)

    @staticmethod
    def _single_value_object(python_type: Any) -> type | None:
        """Return the value object class ``python_type`` names on its own, if any.

        ``Annotated`` wrappers and ``None`` union members are stripped. Any other
        type, including a union with a second non-``None`` member, returns ``None``.
        """
        if typing.get_origin(python_type) is typing.Annotated:
            return IRBuilder._single_value_object(typing.get_args(python_type)[0])
        origin = typing.get_origin(python_type)
        if origin is _types.UnionType or origin is typing.Union:
            args = [a for a in typing.get_args(python_type) if a is not type(None)]
            if len(args) != 1:
                return None
            return IRBuilder._single_value_object(args[0])
        # ``list[Addr]`` and ``dict[str, Addr]`` are generic aliases, not classes,
        # so the class check returns ``None`` for them.
        return python_type if _is_value_object_class(python_type) else None

    def _dict_value_object(self, field: ResolvedField) -> type | None:
        """Return the value object class a ``Dict`` field's values hold, if any."""
        python_type: Any = field._python_type
        if not self._is_dict_type(self._unwrap_type(python_type), python_type):
            return None
        content_type = field.content_type
        return content_type if _is_value_object_class(content_type) else None

    def _dict_field_entry(self, content_type: Any) -> dict[str, Any]:
        """Return the IR entry of a ``Dict`` field.

        The entry always has ``kind`` and ``type``. A typed dict adds its value
        type's short name as ``content_type``. When the value type is a value
        object, it also adds the value object's FQN as ``target``.
        """
        entry: dict[str, Any] = {"kind": "dict", "type": "Dict"}
        if content_type is None:
            return entry
        entry["content_type"] = self._python_type_name(content_type)
        # The short name in ``content_type`` can be ambiguous across modules,
        # so a value-object map also carries the FQN that the schema
        # generators resolve the map's values through.
        if _is_value_object_class(content_type):
            entry["target"] = self._resolved_fqn(content_type)
        return entry

    def _extract_resolved_field(self, field: Any, spec: Any | None) -> dict[str, Any]:
        """Build an IR field dict from a ResolvedField + optional FieldSpec."""
        entry = self._resolved_type_entry(field)
        self._add_identity_flags(field, entry)
        self._add_bounds(field, entry)
        self._add_behaviour_flags(field, entry)
        self._add_spec_attributes(field, spec, entry)
        self._add_default(field, spec, entry)
        return entry

    def _resolved_type_entry(self, field: Any) -> dict[str, Any]:
        """Return the type keys of a resolved field's entry.

        The entry always has ``kind`` and ``type``. A typed list or dict also
        has ``content_type``, and a dict of value objects also has ``target``.
        """
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
            entry = self._dict_field_entry(field.content_type)
        else:
            kind = field.field_kind
            entry["kind"] = kind
            entry["type"] = self._resolve_type_name(base_type, kind)
        return entry

    @staticmethod
    def _add_identity_flags(field: Any, entry: dict[str, Any]) -> None:
        """Add the sparse required, identifier, unique and auto-generated flags."""
        if field.required:
            entry["required"] = True
        if field.identifier:
            entry["identifier"] = True
        if field.unique and not field.identifier:
            # identifier already implies unique; don't duplicate
            entry["unique"] = True
        if field._auto_generated:
            entry["auto_generated"] = True

    def _add_bounds(self, field: Any, entry: dict[str, Any]) -> None:
        """Add the sparse length, value, precision and scale bounds."""
        if field.max_length is not None:
            entry["max_length"] = field.max_length
        if field.min_length is not None:
            entry["min_length"] = field.min_length
        if field.min_value is not None:
            entry["min_value"] = self._ir_bound(field.min_value, entry["type"])
        if field.max_value is not None:
            entry["max_value"] = self._ir_bound(field.max_value, entry["type"])
        # Only a Decimal field's spec carries precision and scale.
        if field.precision is not None:
            entry["precision"] = field.precision
        if field.scale is not None:
            entry["scale"] = field.scale

    @staticmethod
    def _add_behaviour_flags(field: Any, entry: dict[str, Any]) -> None:
        """Add the sparse sanitize, increment, auto-now and description keys."""
        if field.sanitize:
            entry["sanitize"] = True
        if field.increment:
            entry["increment"] = True
        if field.auto_now:
            entry["auto_now"] = True
        if field.auto_now_add:
            entry["auto_now_add"] = True
        if getattr(field, "description", None):
            entry["description"] = field.description

    @staticmethod
    def _add_spec_attributes(
        field: Any, spec: Any | None, entry: dict[str, Any]
    ) -> None:
        """Add choices, transitions and deprecation markers."""
        # Choices — from the original FieldSpec
        if spec is not None and getattr(spec, "choices", None) is not None:
            entry["choices"] = IRBuilder._choices_list(spec.choices)

        # Transitions — from ResolvedField
        if getattr(field, "transitions", None) is not None:
            entry["transitions"] = field.transitions

        # Deprecated — from FieldSpec
        if spec is not None and getattr(spec, "deprecated", None) is not None:
            entry["deprecated"] = spec.deprecated

        # Deprecated ``pickled=`` on ``List`` — the residue marker the ``List``
        # factory leaves on the spec (see ``fields/containers.py``). Surfaced as
        # a sparse flag so ``_check_element_deprecated`` can emit a
        # ``DEPRECATED_FIELD`` diagnostic without re-reading source.
        if spec is not None and getattr(spec, "_pickled_deprecated", False):
            entry["deprecated_pickled"] = True

    @staticmethod
    def _choices_list(choices: Any) -> list[Any]:
        """Return a field's choices as a sorted list of values."""
        if isinstance(choices, type) and issubclass(choices, Enum):
            return sorted(item.value for item in choices)
        choices_iter: Any = choices
        return sorted(str(c) for c in choices_iter)

    def _add_default(self, field: Any, spec: Any | None, entry: dict[str, Any]) -> None:
        """Add the field's default, when it has one."""
        # Default — from FieldSpec for accurate representation. A default JSON
        # cannot encode (a custom type instance, a ``decimal.Decimal``) goes
        # through the field's ``as_dict``, the same serialization the
        # persistence and event paths use.
        if spec is not None:
            if spec.default is not _UNSET:
                entry["default"] = self._default_entry(field, spec.default)
        elif field.default is not None:
            # Fallback to ResolvedField default if no spec. Generated elements —
            # a fact event, a value object projected from an entity — rebuild
            # their fields from ``FieldInfo`` and carry no spec, so a custom
            # default arrives here as a live instance and needs the same
            # serialization.
            entry["default"] = self._default_entry(field, field.default)

    def _default_entry(self, field: Any, default: Any) -> Any:
        """Return the IR value of a default: a marker for a callable."""
        if callable(default):
            return "<callable>"
        return self._serialize_default(field, default)

    @staticmethod
    def _ir_bound(value: Any, ir_type: str) -> Any:
        """Return a JSON-encodable form of a ``min_value`` / ``max_value`` bound.

        JSON cannot encode a ``decimal.Decimal``. On a Decimal field such a
        bound becomes ``str(value)``, which is lossless and keeps trailing
        zeros. On any other field it becomes a number, because the JSON Schema
        generator writes those bounds as ``minimum`` / ``maximum``: an ``int``
        when it is integral on an Integer field, and a ``float`` otherwise, so
        a fractional bound on an Integer field is not rounded to an integer.
        A numeric string bound on an Integer or Float field is converted the
        same way. Every other bound comes back as is.
        """
        if isinstance(value, str) and ir_type in ("Integer", "Float"):
            try:
                value = decimal.Decimal(value)
            except decimal.InvalidOperation:
                # Not a number, so the schema reports it rather than the builder.
                return value
        if not isinstance(value, decimal.Decimal):
            return value
        if ir_type == "Decimal":
            return str(value)
        if (
            ir_type == "Integer"
            and value.is_finite()
            and value == value.to_integral_value()
        ):
            return int(value)
        return float(value)

    @staticmethod
    def _serialize_default(field: Any, default: Any) -> Any:
        """Return a JSON-encodable form of a field's default.

        The IR is written out as JSON (and hashed into the canonical baselines),
        so a default that JSON cannot encode, such as a custom type instance or
        a ``decimal.Decimal``, goes through the field's ``as_dict``. JSON-native
        defaults come back unchanged.
        """
        return field.as_dict(default)

    @staticmethod
    def _unwrap_type(python_type: type | None) -> type | None:
        """Unwrap Optional/Union to get the base concrete type.

        Examples:
            ``float | None``  → ``float``
            ``str | int | UUID``  → ``str``  (first non-None arg)
            ``list[str]``  → ``list[str]``  (unchanged)
            ``Literal['A','B'] | None``  → ``str``  (first Literal arg type)
            ``Annotated[int, PlainValidator(...)]``  → ``int``
        """
        if python_type is None:
            return None

        # A custom field's annotation carries its Pydantic validators and
        # serializers, so the concrete type sits under an ``Annotated`` wrapper.
        # ``Custom`` accepts any class, and a class is free to carry an unrelated
        # ``__metadata__`` attribute, so ask ``get_origin`` instead of sniffing it.
        if typing.get_origin(python_type) is typing.Annotated:
            return IRBuilder._unwrap_type(typing.get_args(python_type)[0])

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

        Handles bare ``dict``, ``dict[K, V]`` (from ``Dict(value_type=...)``),
        and ``dict | list`` (from an untyped ``Dict()`` field).
        """
        if base_type is dict or typing.get_origin(base_type) is dict:
            return True
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
            (decimal.Decimal, "standard"): "Decimal",
            (bool, "standard"): "Boolean",
            (_dt.date, "standard"): "Date",
            (_dt.datetime, "standard"): "DateTime",
        }
        if python_type is not None:
            result = _TYPE_MAP.get((python_type, kind))
            if result:
                return result
            if kind == "custom":
                # A custom field over a primitive stores that primitive —
                # ``as_dict`` hands the value back untouched — so the IR has to
                # name that shape. The schema, Avro and Protobuf generators read
                # this name, and without the lookup ``Custom(int, ...)`` is
                # persisted as an integer but published as a string. An
                # arbitrary class serializes through its own ``to_dict``, whose
                # shape the builder cannot know, so it keeps the String
                # fallback.
                primitive = _TYPE_MAP.get((python_type, "standard"))
                if primitive:
                    return primitive
        return "String"  # Fallback

    @staticmethod
    def _python_type_name(python_type: type | None) -> str:
        """Map a Python type to its IR content_type name."""
        _CONTENT_TYPE_MAP: dict[type, str] = {
            str: "String",
            int: "Integer",
            float: "Float",
            decimal.Decimal: "Decimal",
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
                result.append(self._raw_index_entry(idx))
            elif isinstance(idx, Index):
                result.append(self._index_entry(idx))
        return result

    @staticmethod
    def _raw_index_entry(idx: RawIndex) -> dict[str, Any]:
        """Return the IR summary of a ``RawIndex`` declaration."""
        raw_entry: dict[str, Any] = {
            "raw": True,
            "dialect": idx.dialect,
            "ddl": idx.ddl,
        }
        if idx.name:
            raw_entry["name"] = idx.name
        return raw_entry

    @staticmethod
    def _index_entry(idx: Index) -> dict[str, Any]:
        """Return the IR summary of an ``Index`` declaration."""
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
        return entry

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

        options: dict[str, Any] = {
            "auto_add_id_field": cls.meta_.auto_add_id_field,
            "fact_events": cls.meta_.fact_events,
            "is_event_sourced": cls.meta_.is_event_sourced,
            "limit": cls.meta_.limit,
            "provider": cls.meta_.provider,
            "schema_name": cls.meta_.schema_name,
            "stream_category": cls.meta_.stream_category,
        }
        # Sparse: only emit `reserved` when declared, so aggregates without it
        # get no IR noise. Sorted for a stable, comparable snapshot.
        reserved = getattr(cls.meta_, "reserved", ())
        if reserved:
            options["reserved"] = sorted(set(reserved))
        entry["options"] = dict(sorted(options.items()))

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
    def _extract_resilience_policy(
        element_cls: type[_ElementCls],
    ) -> dict[str, Any] | None:
        """Extract the handler's deadline/retry policy as a sparse IR dict.

        Returns ``None`` when no resilience options are set (sparse IR).
        """
        meta = getattr(element_cls, "meta_", None)
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
            policy["retry_exceptions"] = sorted(
                IRBuilder._retry_exception_name(exc) for exc in retry_exceptions
            )

        return dict(sorted(policy.items())) if policy else None

    @staticmethod
    def _retry_exception_name(exc: Any) -> str:
        """Return the name a ``retry_exceptions`` entry is serialized under."""
        if isinstance(exc, str):
            return exc
        if isinstance(exc, type):
            return fqn(exc)
        # Misconfigured entry (e.g. an exception instance rather than its
        # class) — serialize its class instead of crashing IR materialization
        # with an opaque AttributeError.
        return fqn(type(exc))

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
            "profile": self._subscription_option_name(sub_profile),
            "type": self._subscription_option_name(sub_type),
        }

    @staticmethod
    def _subscription_option_name(value: Any) -> str | None:
        """Return a subscription option's lower-case name, or ``None`` if unset.

        Handler Meta takes either the enum member or its name as a string, so
        both spellings record the same IR value. An unknown string is recorded
        as declared, lower-cased. An empty string is recorded as ``None``, the
        same as an unset option. Any other value is recorded as
        ``str(value).lower()``.
        """
        name = value.value if isinstance(value, Enum) else value
        if name is None:
            return None
        return str(name).lower() or None

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
        sequential_by = getattr(cls.meta_, "sequential_by", None)
        if sequential_by is not None:
            entry["sequential_by"] = sequential_by
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
        sequential_by = getattr(cls.meta_, "sequential_by", None)
        if sequential_by is not None:
            entry["sequential_by"] = sequential_by
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

        sequential_by = getattr(cls.meta_, "sequential_by", None)
        if sequential_by is not None:
            entry["sequential_by"] = sequential_by

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

        # Populate projectors, queries and query handlers
        self._attach_to_projections(
            projections,
            "PROJECTOR",
            "projector_for",
            "projectors",
            self._extract_projector,
        )
        self._attach_to_projections(
            projections, "QUERY", "part_of", "queries", self._extract_query
        )
        self._attach_to_projections(
            projections,
            "QUERY_HANDLER",
            "part_of",
            "query_handlers",
            self._extract_query_handler,
        )

        # Sort inner dicts
        for proj in projections.values():
            for section in ("projectors", "queries", "query_handlers"):
                proj[section] = dict(sorted(proj[section].items()))

        return dict(sorted(projections.items()))

    def _attach_to_projections(
        self,
        projections: dict[str, Any],
        element_type: str,
        owner_option: str,
        section: str,
        extract: Callable[[type[_ElementCls], Any], dict[str, Any]],
    ) -> None:
        """Add each element of ``element_type`` to its projection's ``section``.

        An element whose ``owner_option`` is unset, or names a class that is not
        a registered projection, is left out.
        """
        registry = self._domain._domain_registry
        for record in registry._elements.get(element_type, {}).values():
            cls = record.cls
            owner = getattr(cls.meta_, owner_option, None)
            if owner is None:
                continue
            proj_fqn = fqn(owner)
            if proj_fqn in projections:
                projections[proj_fqn][section][fqn(cls)] = extract(cls, record)

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
        sequential_by = getattr(cls.meta_, "sequential_by", None)
        if sequential_by is not None:
            entry["sequential_by"] = sequential_by
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
        for section, entries in flows.items():
            flows[section] = dict(sorted(entries.items()))

        return flows

    # ------------------------------------------------------------------
    # Cluster assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_aggregate_cls(element_cls: type[_ElementCls]) -> type | None:
        """Resolve the root aggregate class for an element.

        Tries ``aggregate_cluster`` first (set by resolver for entities,
        commands, events), then falls back to traversing ``part_of``
        (needed for fact events generated after cluster assignment).
        """

        agg: type | None = getattr(element_cls.meta_, "aggregate_cluster", None)
        if agg is not None:
            return agg

        part_of = getattr(element_cls.meta_, "part_of", None)
        while part_of is not None:
            if isinstance(part_of, type) and issubclass(part_of, BaseAggregate):
                return part_of
            part_of = getattr(getattr(part_of, "meta_", None), "part_of", None)
        return None

    def _embedded_vo_fqn(self, field_obj: Any) -> str | None:
        """Return the FQN of the value object a field embeds, or ``None``.

        Covers ``ValueObject`` and ``ValueObjectList`` fields and a ``Dict``
        field whose values are a value object.
        """
        if isinstance(field_obj, ValueObject):
            return self._resolved_fqn(field_obj.value_object_cls)
        if isinstance(field_obj, ValueObjectList):
            if isinstance(field_obj.content_type, ValueObject):
                return self._resolved_fqn(field_obj.content_type.value_object_cls)
            return fqn(field_obj.content_type)
        if isinstance(field_obj, ResolvedField):
            dict_vo = self._dict_value_object(field_obj)
            if dict_vo is not None:
                return self._resolved_fqn(dict_vo)
        return None

    def _build_vo_cluster_map(self) -> dict[str, type]:
        """Build a mapping of VO FQN → aggregate class from fields and ``part_of``.

        Value objects don't get ``aggregate_cluster`` set by the resolver,
        so we derive it from which aggregate/entity embeds them via
        ``ValueObject``, ``ValueObjectList`` or value-object ``Dict`` fields,
        then from an explicit ``part_of``. A value object none of these place
        goes to the aggregate of a command or event that holds it in a
        single-value field; a list or dict field on a message does not place it.
        """
        vo_map: dict[str, type] = {}

        # Scan aggregates and entities for VO field references
        self._map_embedded_value_objects(vo_map)

        # Also check VOs that have explicit part_of
        self._map_part_of_value_objects(vo_map)

        # Last, value objects held only by commands and events. Running after
        # the scans above means a value object an aggregate, an entity or
        # ``part_of`` places keeps that cluster.
        self._map_message_value_objects(vo_map)

        return vo_map

    def _map_embedded_value_objects(self, vo_map: dict[str, type]) -> None:
        """Add to ``vo_map`` each value object an aggregate or entity field embeds.

        A value object already in ``vo_map`` keeps its cluster.
        """
        registry = self._domain._domain_registry
        for element_type in ("AGGREGATE", "ENTITY"):
            for record in registry._elements.get(element_type, {}).values():
                owner_cls = record.cls
                # For entities, use their aggregate cluster; for aggregates, use self
                agg_cls = getattr(owner_cls.meta_, "aggregate_cluster", owner_cls)

                for field_obj in declared_fields(owner_cls).values():
                    vo_fqn = self._embedded_vo_fqn(field_obj)
                    if vo_fqn is not None and vo_fqn not in vo_map:
                        vo_map[vo_fqn] = agg_cls

    def _map_part_of_value_objects(self, vo_map: dict[str, type]) -> None:
        """Add to ``vo_map`` each value object that declares ``part_of``.

        A value object already in ``vo_map`` keeps its cluster.
        """
        registry = self._domain._domain_registry
        for record in registry._elements.get("VALUE_OBJECT", {}).values():
            vo_fqn = fqn(record.cls)
            if vo_fqn not in vo_map:
                part_of = getattr(record.cls.meta_, "part_of", None)
                if part_of is not None:
                    vo_map[vo_fqn] = part_of

    def _map_message_value_objects(self, vo_map: dict[str, type]) -> None:
        """Add to ``vo_map`` each value object a message's single-value field holds.

        A value object already in ``vo_map`` keeps its cluster. When messages of
        two aggregates hold the same value object, the first message scanned
        wins: commands are scanned before events, each in registration order.
        Messages with no resolvable aggregate, such as an abstract base event,
        are skipped.
        """
        registry = self._domain._domain_registry
        for element_type in ("COMMAND", "EVENT"):
            for record in registry._elements.get(element_type, {}).values():
                message_cls = record.cls
                agg_cls = self._resolve_aggregate_cls(message_cls)
                if agg_cls is None:
                    continue
                for vo_cls in self._message_value_objects(message_cls):
                    vo_map.setdefault(self._resolved_fqn(vo_cls), agg_cls)

    def _message_value_objects(self, message_cls: Any) -> list[type]:
        """Return the value object classes the fields of a command or event hold."""
        vo_classes: list[type] = []
        for field_obj in declared_fields(message_cls).values():
            if isinstance(field_obj, ResolvedField):
                vo_cls = self._message_value_object(message_cls, field_obj)
                if vo_cls is not None:
                    vo_classes.append(vo_cls)
        return vo_classes

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

        sections = (
            ("ENTITY", "entities", self._extract_entity),
            ("COMMAND", "commands", self._extract_command),
            ("EVENT", "events", self._extract_event),
            ("COMMAND_HANDLER", "command_handlers", self._extract_command_handler),
            ("EVENT_HANDLER", "event_handlers", self._extract_event_handler),
            (
                "APPLICATION_SERVICE",
                "application_services",
                self._extract_application_service,
            ),
            ("REPOSITORY", "repositories", self._extract_repository),
            ("DATABASE_MODEL", "database_models", self._extract_database_model),
        )
        for element_type_key, section, extractor in sections:
            self._place_in_cluster(clusters, element_type_key, section, extractor)

        # Populate value objects (derive cluster from field references)
        self._place_value_objects(clusters)

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

    def _place_in_cluster(
        self,
        clusters: dict[str, Any],
        element_type_key: str,
        section: str,
        extractor: Callable[[type[_ElementCls], Any], dict[str, Any]],
    ) -> None:
        """Place each element of ``element_type_key`` in its aggregate's ``section``.

        An element whose aggregate is unresolved or has no cluster is left out.
        """
        registry = self._domain._domain_registry
        for record in registry._elements.get(element_type_key, {}).values():
            cls = record.cls
            agg_cls = self._resolve_aggregate_cls(cls)
            if agg_cls is not None:
                agg_fqn = fqn(agg_cls)
                if agg_fqn in clusters:
                    clusters[agg_fqn][section][fqn(cls)] = extractor(cls, record)

    def _place_value_objects(self, clusters: dict[str, Any]) -> None:
        """Place each value object in the cluster that embeds or owns it."""
        registry = self._domain._domain_registry
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

    # ------------------------------------------------------------------
    # Method edges (raise / invoke derivation)
    # ------------------------------------------------------------------

    def _materialize_method_edges(self, ir: dict[str, Any]) -> None:
        """Write ``method_edges`` onto the elements that own the methods.

        A post-pass over the already-assembled ``clusters``, ``flows`` and
        ``projections`` sections. ``raises`` is derived for aggregates and
        entities by co-location (an EVENT constructed in a method that also
        calls ``raise_``); ``invokes`` is derived for command handlers, event
        handlers, projectors and process managers by matching a call's method
        name against exactly one method of the elements in scope. Both derivations
        fail open: an element whose source cannot be read yields no edges and the
        build still succeeds.
        """
        fqn_to_cls, event_fqns = self._registered_classes_and_events()
        clusters = ir["clusters"]
        type_to_aggs = self._message_type_clusters(clusters)
        surfaces = _ClusterSurfaces(self.view, clusters, fqn_to_cls)

        # raises: aggregates and entities.
        self._apply_raise_edges(clusters, fqn_to_cls, event_fqns)

        # invokes: command and event handlers, scoped to their own cluster.
        for agg_fqn, cluster in clusters.items():
            surface = surfaces._cluster(agg_fqn)
            for section in ("command_handlers", "event_handlers"):
                for handler_fqn, handler_entry in cluster[section].items():
                    invoke_edges = self._invoke_edges(fqn_to_cls[handler_fqn], surface)
                    if invoke_edges:
                        handler_entry["method_edges"] = invoke_edges

        # invokes: process managers (flows) and projectors (projections), each
        # scoped to the union of the clusters the messages it handles reach.
        for pm_fqn, pm_entry in ir["flows"]["process_managers"].items():
            self._apply_handler_invokes(
                pm_fqn, pm_entry, fqn_to_cls, type_to_aggs, surfaces._union
            )
        for proj_group in ir["projections"].values():
            for projector_fqn, projector_entry in proj_group["projectors"].items():
                self._apply_handler_invokes(
                    projector_fqn,
                    projector_entry,
                    fqn_to_cls,
                    type_to_aggs,
                    surfaces._union,
                )

    def _registered_classes_and_events(self) -> tuple[dict[str, type], set[str]]:
        """Return ``fqn(cls)`` -> cls for every registered element, and the EVENT names.

        The first map resolves an assembled section's string keys (which the
        builder writes as ``fqn(cls)``) back to a class. The set holds the
        registered EVENT names, so only an event construction counts toward
        ``raises``. It is keyed by the registry's own ``qualname``, which is
        what a ``ConstructionFact.fqn`` is matched against (the facts layer
        recognizes an element by the name the registry recorded, not by the
        class's current ``__module__``).
        """
        registry = self._domain._domain_registry
        fqn_to_cls: dict[str, type] = {}
        event_fqns: set[str] = set()
        for element_type, records in registry._elements.items():
            for record in records.values():
                fqn_to_cls[fqn(record.cls)] = record.cls
                if element_type == "EVENT":
                    event_fqns.add(record.qualname)
        return fqn_to_cls, event_fqns

    @staticmethod
    def _message_type_clusters(clusters: dict[str, Any]) -> dict[str, set[str]]:
        """Return message ``__type__`` -> the aggregate clusters that own it.

        A command or event named in more than one cluster maps to each, which
        only widens an invoke scope (and so makes an ambiguous name more likely
        to be skipped, never wrongly matched).
        """
        type_to_aggs: dict[str, set[str]] = {}
        for agg_fqn, cluster in clusters.items():
            for section in ("commands", "events"):
                for entry in cluster[section].values():
                    type_key = entry.get("__type__")
                    if type_key:
                        type_to_aggs.setdefault(type_key, set()).add(agg_fqn)
        return type_to_aggs

    def _apply_raise_edges(
        self,
        clusters: dict[str, Any],
        fqn_to_cls: dict[str, type],
        event_fqns: set[str],
    ) -> None:
        """Write ``raises`` edges onto every aggregate and entity entry."""
        for agg_fqn, cluster in clusters.items():
            raise_edges = self._raise_edges(fqn_to_cls[agg_fqn], event_fqns)
            if raise_edges:
                cluster["aggregate"]["method_edges"] = raise_edges
            for ent_fqn, ent_entry in cluster["entities"].items():
                raise_edges = self._raise_edges(fqn_to_cls[ent_fqn], event_fqns)
                if raise_edges:
                    ent_entry["method_edges"] = raise_edges

    def _apply_handler_invokes(
        self,
        element_fqn: str,
        entry: dict[str, Any],
        fqn_to_cls: dict[str, type],
        type_to_aggs: dict[str, set[str]],
        union_surface: Any,
    ) -> None:
        """Derive ``invokes`` for a handler whose scope is its handled messages.

        Shared by process managers and projectors: neither has a ``part_of``
        cluster, so the scope is the union of the clusters the ``__type__`` keys
        in its ``handlers`` map resolve to. A handled type that no cluster owns
        (an external message) contributes nothing; if none resolve, the handler
        gets no edges.
        """
        agg_fqns: set[str] = set()
        for handled_type in entry.get("handlers", {}):
            agg_fqns |= type_to_aggs.get(handled_type, set())
        if not agg_fqns:
            return
        edges = self._invoke_edges(fqn_to_cls[element_fqn], union_surface(agg_fqns))
        if edges:
            entry["method_edges"] = edges

    def _raise_edges(
        self, cls: type, event_fqns: set[str]
    ) -> dict[str, dict[str, list[str]]]:
        """The ``raises`` edges of an element, method name -> ``{"raises": [...]}``.

        A method contributes only when it calls ``raise_`` (by the called
        method's name, whatever the receiver role, so the ``user.raise_(...)``
        factory idiom counts). Every EVENT constructed anywhere in that method is
        recorded, sorted and de-duplicated — the accepted co-location over-report.
        A method with no ``raise_`` call, or one that builds no registered event,
        contributes nothing.
        """
        edges: dict[str, dict[str, list[str]]] = {}
        for method_name, facts in self.view.element_facts(cls).items():
            if not any(call.method == RAISE_METHOD for call in facts.calls):
                continue
            raised = sorted({c.fqn for c in facts.constructions if c.fqn in event_fqns})
            if raised:
                edges[method_name] = {"raises": raised}
        return dict(sorted(edges.items()))

    def _invoke_edges(
        self, cls: type, surface: dict[str, list[tuple[str, str]]]
    ) -> dict[str, dict[str, list[dict[str, str]]]]:
        """The ``invokes`` edges of a handler, method name -> ``{"invokes": [...]}``.

        For each call written in a handler method, its trailing method name is
        looked up in the scope's name surface. A name that maps to exactly one
        ``(element_fqn, method)`` pair records that edge; a name that maps to more
        than one is ambiguous and records nothing (skip, never guess). Edges are
        de-duplicated and sorted by ``(element, method)`` for a stable baseline.
        """
        edges: dict[str, dict[str, list[dict[str, str]]]] = {}
        for method_name, facts in self.view.element_facts(cls).items():
            targets: set[tuple[str, str]] = set()
            for call in facts.calls:
                if call.method is None:
                    continue
                matches = surface.get(call.method)
                if not matches or len(matches) != 1:
                    continue
                targets.add(matches[0])
            if targets:
                edges[method_name] = {
                    "invokes": [
                        {"element": elem_fqn, "method": target_method}
                        for elem_fqn, target_method in sorted(targets)
                    ]
                }
        return dict(sorted(edges.items()))

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

    def _build_enrichers(self) -> dict[str, list[str]]:
        """List the registered enrichers by qualified name, per kind.

        Each list keeps registration order, because enrichers run in that
        order and a later one can overwrite what an earlier one set. A kind
        with no enrichers is left out.
        """
        registered = {
            "aggregate": self._domain._aggregate_enrichers,
            "command": self._domain._command_enrichers,
            "event": self._domain._event_enrichers,
        }
        return {
            kind: [_callable_qualname(fn) for fn in enrichers]
            for kind, enrichers in registered.items()
            if enrichers
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
        self._diagnose_unsourced_projection_field(ir)
        self._diagnose_upcaster_gap(ir)
        self._diagnose_cross_aggregate_reference(ir)
        self._diagnose_es_aggregate_no_events(ir)
        self._diagnose_value_object_mutable_field(ir)
        self._diagnose_circular_cluster_dependencies(ir)
        self._diagnose_infra_imports(ir)
        self._diagnose_adapter_calls(ir)
        self._diagnose_query_handler_without_query(ir)
        self._diagnose_projector_handles_orphaned_event(ir)
        self._diagnose_command_handler_cross_cluster(ir)
        self._diagnose_unbounded_indexed_string(ir)
        self._diagnose_unindexed_filter_path(ir)
        self._diagnose_event_handler_foreign_event(ir)
        # Info-level rules (design smells)
        self._diagnose_handler_persists_and_calls_out(ir)
        self._diagnose_unraised_event(ir)
        self._diagnose_aggregate_too_large(ir)
        self._diagnose_handler_too_broad(ir)
        self._diagnose_event_without_data(ir)
        self._diagnose_subscriber_no_streams(ir)
        self._diagnose_process_manager_unclosed(ir)
        self._diagnose_deprecated_elements(ir)
        self._diagnose_deprecated_options(ir)
        self._diagnose_deprecated_imports(ir)
        self._diagnose_aggregate_no_invariants(ir)
        self._diagnose_event_not_past_tense(ir)
        self._diagnose_command_not_imperative(ir)
        self._diagnose_aggregate_not_noun(ir)
        # Custom lint rules from config
        self._run_custom_lint_rules(ir)
        # Suppression stage — runs last so custom-rule findings are also
        # subject to per-element ``suppress_checks`` and ``[lint].suppressions``.
        self._apply_suppressions()

    def _diagnose_circular_cluster_dependencies(self, ir: dict[str, Any]) -> None:
        """Report CIRCULAR_CLUSTER_DEPENDENCY for each aggregate cluster on a
        directed cycle of cross-cluster references.

        An edge is a ``reference`` field whose target is another cluster's
        aggregate root. A reference inside one cluster, including a child
        entity's back-pointer to its root, is not an edge. Each cluster on a
        cycle is reported once, even when it sits on more than one cycle, and
        the output order is deterministic.
        """
        # 1. Build adjacency: cluster_fqn -> sorted list of target cluster FQNs.
        adjacency = self._cluster_adjacency(ir["clusters"])

        # 2. One diagnostic per cluster in each cyclic component. Every cluster in
        #    a strongly connected component is reachable from every other, so
        #    the whole component is on a cycle. A component of
        #    size >= 2 is exactly the set of mutually-dependent clusters (a
        #    self-loop is impossible here — ``target != cluster_fqn`` guards it).
        for component in self._strongly_connected_components(adjacency):
            if len(component) >= 2:
                self._emit_cluster_cycle(component)

    @staticmethod
    def _cluster_adjacency(clusters: dict[str, Any]) -> dict[str, list[str]]:
        """Return cluster FQN -> sorted FQNs of the clusters it references."""
        cluster_fqns = set(clusters.keys())
        return {
            cluster_fqn: IRBuilder._referenced_clusters(
                cluster_fqn, cluster, cluster_fqns
            )
            for cluster_fqn, cluster in clusters.items()
        }

    @staticmethod
    def _referenced_clusters(
        cluster_fqn: str, cluster: dict[str, Any], cluster_fqns: set[str]
    ) -> list[str]:
        """Return the sorted other clusters a cluster's ``reference`` fields target."""
        targets: set[str] = set()
        entities = [cluster["aggregate"], *cluster["entities"].values()]
        for element in entities:
            for field in element.get("fields", {}).values():
                if field.get("kind") != "reference":
                    continue
                target = field.get("target")
                if target in cluster_fqns and target != cluster_fqn:
                    targets.add(target)
        return sorted(targets)

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
        return _TarjanSCC(adjacency)._components()

    def _emit_cluster_cycle(self, component: list[str]) -> None:
        """Append one CIRCULAR_CLUSTER_DEPENDENCY diagnostic per cluster in the
        strongly-connected component, naming the whole mutually-dependent group
        so the reported set is stable and each cluster is reported once."""
        group = ", ".join(f"`{fqn}`" for fqn in component)
        for cluster_fqn in component:
            self._diagnostics.append(
                build_diagnostic(
                    DiagnosticCode.CIRCULAR_CLUSTER_DEPENDENCY,
                    element=cluster_fqn,
                    message=f"Cluster `{cluster_fqn}` participates in a circular "
                    f"dependency among clusters: {group}",
                )
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

        # module -> True/False cache of "imports infra", to parse each file once.
        module_flags: dict[str, bool] = {}

        # Iterate every non-internal registered element in a stable (fqn) order
        # so emitted diagnostics are deterministic.
        scanned: list[tuple[str, str, str]] = []  # (fqn, name, module)
        for element_fqn, cls in self._unique_registered_elements():
            module = getattr(cls, "__module__", None)
            if module:
                scanned.append((element_fqn, cls.__name__, module))

        for element_fqn, name, module in sorted(scanned):
            if self._module_imports_infra(module, module_flags):
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.INFRA_IMPORT_IN_DOMAIN,
                        element=element_fqn,
                        message=f"Domain element `{name}` "
                        f"(module `{module}`) imports from "
                        f"`protean.adapters`.",
                    )
                )

    def _unique_registered_elements(self) -> list[tuple[str, type]]:
        """Return ``(fqn, cls)`` of each non-internal registered element.

        The list is in registry order, and an FQN registered more than once
        appears only the first time.
        """
        registry = self._domain._domain_registry
        seen: set[str] = set()
        elements: list[tuple[str, type]] = []
        for records in registry._elements.values():
            for record in records.values():
                if record.internal:
                    continue
                element_fqn = fqn(record.cls)
                if element_fqn in seen:
                    continue
                seen.add(element_fqn)
                elements.append((element_fqn, record.cls))
        return elements

    def _module_imports_infra(self, module: str, module_flags: dict[str, bool]) -> bool:
        """Return whether ``module`` imports ``protean.adapters`` at its top level.

        The answer is cached in ``module_flags``.
        """
        if module in module_flags:
            return module_flags[module]
        flag = False
        # Fails open: an unresolvable, unreadable or unparseable module
        # yields no tree, and is treated as not importing infra.
        tree = self.source.tree(module)
        if tree is not None:
            flag = any(
                _is_adapters_name(n)
                for node in self._module_level_imports(tree)
                for n in self._import_names(node)
            )
        module_flags[module] = flag
        return flag

    @staticmethod
    def _module_level_imports(tree: ast.Module) -> list[ast.stmt]:
        """Import statements at the module's top level only.

        Nested imports are deliberately excluded: a ``TYPE_CHECKING`` guard,
        an ``except ImportError`` fallback, or a function-local lazy import
        introduce no runtime coupling — they are the idiomatic ways to
        *avoid* it — so flagging them would be a false positive.
        """
        return [
            node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
        ]

    @staticmethod
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

    def _diagnose_adapter_calls(self, ir: dict[str, Any]) -> None:
        """Report ADAPTER_CALL_IN_DOMAIN for each call in a registered element's
        method whose callee statically resolves under ``protean.adapters``.

        Runs only when ``[lint].check_adapter_calls`` is true. Emits one
        diagnostic per call-site. A callee that does not resolve is skipped.
        """
        if not self._domain.config.get("lint", {}).get("check_adapter_calls", False):
            return

        # Iterate every non-internal registered element in a stable (fqn) order
        # so emitted diagnostics are deterministic; dedupe by FQN as the
        # module-import rule does.
        scanned = self._unique_registered_elements()
        for element_fqn, cls in sorted(scanned, key=lambda pair: pair[0]):
            self._diagnose_adapter_calls_in(element_fqn, cls)

    def _diagnose_adapter_calls_in(self, element_fqn: str, cls: type) -> None:
        """Report ADAPTER_CALL_IN_DOMAIN for each adapter call in one element."""
        name = cls.__name__
        # Facts come method-name-ordered, calls within a method in source
        # order — so one diagnostic per adapter call-site, in a stable order.
        for method_name, facts in self.view.element_facts(cls).items():
            for call in facts.calls:
                callee = call.callee_fqn
                if callee is None or not _is_adapters_name(callee):
                    continue
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.ADAPTER_CALL_IN_DOMAIN,
                        element=element_fqn,
                        message=f"Domain element `{name}` calls "
                        f"`{callee}` in method `{method_name}` "
                        f"(line {call.location.line}), coupling the "
                        f"domain to `protean.adapters`.",
                    )
                )

    def _diagnose_event_handler_foreign_event(self, ir: dict[str, Any]) -> None:
        """EVENT_HANDLER_FOREIGN_EVENT: an event handler whose ``part_of``
        cluster differs from the cluster that owns an event it handles.

        Scope is ``event_handlers`` only. Projectors and process managers are
        designed to consume events across clusters, so they are excluded by
        construction — this rule never reads ``ir["projections"]`` or
        ``ir["flows"]``. A handled ``__type__`` owned by no cluster, or owned
        ambiguously by more than one cluster (``__type__`` encodes only the
        domain and class name, so same-named events in different clusters
        collide), is not flagged — there is no single deterministic owner to
        compare against.
        """
        type_to_owner = self._event_type_owners(ir["clusters"])

        for handler_cluster_fqn, cluster in ir["clusters"].items():
            handler_cluster_name = cluster["aggregate"]["name"]
            for eh in cluster["event_handlers"].values():
                self._diagnose_foreign_events_of(
                    eh, handler_cluster_fqn, handler_cluster_name, type_to_owner
                )

    @staticmethod
    def _event_type_owners(
        clusters: dict[str, Any],
    ) -> dict[str, tuple[str, str, str] | None]:
        """Return event ``__type__`` -> (cluster FQN, cluster name, event name).

        A ``__type__`` that more than one cluster owns maps to ``None``.
        """
        type_to_owner: dict[str, tuple[str, str, str] | None] = {}
        for cluster_fqn, cluster in clusters.items():
            for event in cluster["events"].values():
                event_type = event.get("__type__")
                if not event_type:
                    continue
                if event_type in type_to_owner:
                    # Collision: __type__ owned by more than one cluster.
                    # No single deterministic owner — treat like an orphan.
                    type_to_owner[event_type] = None
                else:
                    type_to_owner[event_type] = (
                        cluster_fqn,
                        cluster["aggregate"]["name"],
                        event["name"],
                    )
        return type_to_owner

    def _diagnose_foreign_events_of(
        self,
        eh: dict[str, Any],
        handler_cluster_fqn: str,
        handler_cluster_name: str,
        type_to_owner: dict[str, tuple[str, str, str] | None],
    ) -> None:
        """Report EVENT_HANDLER_FOREIGN_EVENT for each foreign event ``eh`` handles."""
        for handled_type in eh.get("handlers", {}):
            owner = type_to_owner.get(handled_type)
            if owner is None:
                continue
            owner_cluster_fqn, owner_cluster_name, event_name = owner
            if owner_cluster_fqn == handler_cluster_fqn:
                continue
            self._diagnostics.append(
                build_diagnostic(
                    DiagnosticCode.EVENT_HANDLER_FOREIGN_EVENT,
                    element=eh["fqn"],
                    message=f"{eh['name']} (part_of {handler_cluster_name}) "
                    f"handles event {event_name}, owned by "
                    f"cluster {owner_cluster_name}. Cross-cluster "
                    f"event handling couples two aggregates; "
                    f"consider a ProcessManager to mediate the "
                    f"interaction if the events have causal "
                    f"dependencies.",
                )
            )

    def _apply_suppressions(self) -> None:
        """Remove suppressed diagnostics from :attr:`_diagnostics`.

        Applies two suppressions in order:

        1. An element's ``suppress_checks`` option removes the named codes from
           that element's diagnostics. It works for every registered element
           type, including events, commands and value objects.
        2. ``[lint].suppressions``, a ``{code: N}`` map, removes the first ``N``
           remaining diagnostics of each code in ``(code, element, field,
           message)`` order.

        Runs after the custom lint rules and before the final sort in
        :meth:`build`.

        Raises:
            ConfigurationError: If ``[lint].suppressions`` is malformed.
        """
        # 1. Drop each diagnostic its element suppresses.
        fqn_suppress = self._element_suppressions()
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
        kept: list[Diagnostic | dict[str, Any]] = []
        for d in survivors:
            code = d.get("code", "")
            seen[code] = seen.get(code, 0) + 1
            if seen[code] <= suppressions.get(code, 0):
                continue
            kept.append(d)

        self._diagnostics = kept

    def _element_suppressions(self) -> dict[str, set[str]]:
        """Return element FQN -> the codes its ``suppress_checks`` option names.

        Elements that suppress nothing are left out.
        """
        registry = self._domain._domain_registry

        # FQN -> suppressed codes, read from the registry because events,
        # commands and value objects carry no IR ``options`` block.
        # ``getattr(..., ()) or ()`` is defensive:
        # element types whose Root never declared the ``suppress_checks``
        # option (e.g. UPCASTER) carry no ``suppress_checks`` key on
        # ``meta_``, so the stage must not assume the option's presence — it
        # guards a missing *option*, not a missing ``meta_``. A bare string
        # is normalised to a single-code tuple so ``suppress_checks="CODE"``
        # is not iterated character-by-character.
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
        return fqn_suppress

    def _diagnose_unhandled_events(self, ir: dict[str, Any]) -> None:
        """UNHANDLED_EVENT: events with no registered handler.

        Excludes published events (intentionally external), fact events
        (auto-generated), and auto-generated events (e.g. process manager
        transition events).
        """
        handled_event_types = self._handled_event_types(ir)

        # Check each event
        for cluster in ir["clusters"].values():
            for event in cluster["events"].values():
                if self._expects_no_handler(event):
                    continue

                event_type = event.get("__type__", "")
                if event_type and event_type not in handled_event_types:
                    self._diagnostics.append(
                        build_diagnostic(
                            DiagnosticCode.UNHANDLED_EVENT,
                            element=event["fqn"],
                            message=f"Event {event['name']} has no registered handler",
                        )
                    )

    @staticmethod
    def _handled_event_types(ir: dict[str, Any]) -> set[str]:
        """Return every ``__type__`` an event handler, projector or PM handles."""
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

        return handled_event_types

    @staticmethod
    def _expects_no_handler(event: dict[str, Any]) -> bool:
        """Return whether an event is exempt from UNHANDLED_EVENT."""
        # Skip published events — they are intentionally external
        if event.get("published", False):
            return True
        # Skip fact events — auto-generated from aggregate changes
        if event.get("is_fact_event", False):
            return True
        # Skip auto-generated events (e.g. PM transition events)
        return bool(event.get("auto_generated", False))

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
                        build_diagnostic(
                            DiagnosticCode.UNUSED_COMMAND,
                            element=command["fqn"],
                            message=f"Command {command['name']} has no registered handler",
                        )
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
                        build_diagnostic(
                            DiagnosticCode.ES_EVENT_MISSING_APPLY,
                            element=event_fqn,
                            message=f"Event {event['name']} has no @apply handler "
                            f"on aggregate {aggregate['name']}",
                        )
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
                build_diagnostic(
                    DiagnosticCode.PUBLISHED_NO_EXTERNAL_BROKER,
                    element=self._domain.name,
                    message="Domain has published events but no external_brokers "
                    "configured in outbox settings. Published events will "
                    "only be dispatched internally.",
                )
            )

    def _diagnose_aggregate_without_command_handler(self, ir: dict[str, Any]) -> None:
        """AGGREGATE_WITHOUT_COMMAND_HANDLER: aggregate with no write path.

        An aggregate cluster that has no command handlers has no way to
        receive commands — likely a wiring gap.  Internal/infrastructure
        aggregates (from ``protean.adapters``) and abstract aggregates are
        excluded: an abstract base is never instantiated, so its concrete
        subclasses carry the write path.
        """
        abstract_fqns = self._abstract_aggregate_fqns()
        for cluster in ir["clusters"].values():
            aggregate = cluster["aggregate"]
            # Skip infrastructure aggregates (e.g. MemoryMessage)
            if aggregate["fqn"].startswith("protean.adapters."):
                continue
            if aggregate["fqn"] in abstract_fqns:
                continue
            if not cluster["command_handlers"]:
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.AGGREGATE_WITHOUT_COMMAND_HANDLER,
                        element=aggregate["fqn"],
                        message=f"Aggregate `{aggregate['name']}` has no command handler, "
                        f"so no write path exists",
                    )
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
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.PROJECTION_WITHOUT_PROJECTOR,
                        element=proj["fqn"],
                        message=f"Projection `{proj['name']}` has no projector "
                        f"to populate it",
                    )
                )

    def _diagnose_unsourced_projection_field(self, ir: dict[str, Any]) -> None:
        """Report UNSOURCED_PROJECTION_FIELD for each projection field that no
        projector method writes.

        A field is written when any method of any projector of the projection
        constructs the projection with the field as a keyword, or assigns an
        attribute of that name. Helper methods count as well as ``@on``
        handlers. A delete, or a write on a handler's parameter or a helper's
        receiver, does not count. Emits nothing for a projection that is
        ``externally_populated``, that is constructed with a ``**kwargs`` splat
        or a positional template, or whose projectors show no write to any of
        its fields. The ``identity_field`` is never reported.
        """
        registry = self._domain._domain_registry
        projector_cls_by_fqn = {
            fqn(record.cls): record.cls
            for record in registry._elements.get("PROJECTOR", {}).values()
        }

        for proj_entry in ir["projections"].values():
            proj = proj_entry["projection"]
            if proj.get("options", {}).get("externally_populated"):
                continue

            written, dynamic = self._projection_writes(
                proj, proj_entry["projectors"], projector_cls_by_fqn
            )

            # A dynamic construction anywhere in the union makes the field set
            # unknowable; the evidence guard trips only when the union is empty.
            if dynamic or not written:
                continue

            self._emit_unsourced_projection_fields(proj, written)

    def _projection_writes(
        self,
        proj: dict[str, Any],
        projectors: dict[str, Any],
        projector_cls_by_fqn: dict[str, type],
    ) -> tuple[set[str], bool]:
        """Return the projection fields its projectors write, and a dynamic flag.

        The flag is ``True`` when any projector method builds the projection
        from a ``**kwargs`` splat or a positional template.
        """
        written: set[str] = set()
        dynamic = False
        for projector_fqn, projector_entry in projectors.items():
            cls = projector_cls_by_fqn.get(projector_fqn)
            entry = self.view.element_class_entry(cls) if cls is not None else None
            if entry is None:
                continue
            if self._projector_writes(entry, projector_entry, proj, written):
                dynamic = True
        return written, dynamic

    def _projector_writes(
        self,
        entry: Any,
        projector_entry: dict[str, Any],
        proj: dict[str, Any],
        written: set[str],
    ) -> bool:
        """Add the projection fields one projector writes to ``written``.

        Returns whether any of its methods builds the projection dynamically.
        """
        proj_fqn = proj["fqn"]
        proj_fields = proj.get("fields", {})
        handler_names = {
            name
            for names in projector_entry.get("handlers", {}).values()
            for name in names
        }
        dynamic = False
        for method in entry.methods:
            facts = self.view.method_facts(entry.module, method.node)
            if self._record_constructions(facts, proj_fqn, written):
                dynamic = True
            writes = self._record_attribute_writes(
                entry, method, facts, proj_fields, handler_names
            )
            written.update(attribute.name for attribute in writes)
        return dynamic

    @staticmethod
    def _record_constructions(facts: Any, proj_fqn: str, written: set[str]) -> bool:
        """Add the fields each construction of ``proj_fqn`` names to ``written``.

        Returns whether any such construction is dynamic.
        """
        dynamic = False
        for construction in facts.constructions:
            if construction.fqn != proj_fqn:
                continue
            # Only a construction can disable the rule. A
            # ``QuerySet.update(**data)`` also fills fields from a
            # mapping, but its ``CallFact`` carries only the callee
            # name, so it cannot be told apart from ``dict.update``.
            if construction.dynamic_kwargs or (construction.positional_template):
                dynamic = True
            written.update(construction.field_names)
        return dynamic

    def _record_attribute_writes(
        self,
        entry: Any,
        method: Any,
        facts: Any,
        proj_fields: dict[str, Any],
        handler_names: set[str],
    ) -> list[Any]:
        """Return a method's attribute writes that can be writes to the record."""
        writes = [
            attribute
            for attribute in facts.attributes
            if attribute.is_write
            and not attribute.is_delete
            and attribute.name in proj_fields
        ]
        if not writes:
            return writes
        if method.name in handler_names:
            # A handler's parameters are the projector and the
            # message, never the record, so a write on one is
            # provably not a record write. Asking for the flow
            # costs a walk, so ask only when there is a write to
            # judge.
            excluded = {
                definition.name
                for definition in self.view.method_flow(
                    entry.module, method.node
                ).parameters
            }
        else:
            excluded = self._helper_receiver(method)
        return [attribute for attribute in writes if attribute.receiver not in excluded]

    @staticmethod
    def _helper_receiver(method: Any) -> set[str]:
        """Return the receiver parameter name of a non-static helper method."""
        # A helper's parameter often *is* the record
        # (``_apply(self, record, event)``), so only its
        # receiver is dropped: the first parameter of a
        # non-static method is the projector, never a
        # record.
        positional = method.node.args.posonlyargs or method.node.args.args
        return (
            {positional[0].arg}
            if positional and "staticmethod" not in method.decorators
            else set()
        )

    def _emit_unsourced_projection_fields(
        self, proj: dict[str, Any], written: set[str]
    ) -> None:
        """Report UNSOURCED_PROJECTION_FIELD for each unwritten projection field."""
        proj_fqn = proj["fqn"]
        identity_field = proj.get("identity_field")
        exempt = {identity_field} if identity_field is not None else set()
        for field_name in proj.get("fields", {}):
            if field_name in written or field_name in exempt:
                continue
            self._diagnostics.append(
                build_diagnostic(
                    DiagnosticCode.UNSOURCED_PROJECTION_FIELD,
                    element=proj_fqn,
                    message=f"Field `{field_name}` on projection "
                    f"`{proj['name']}` is filled by no projector write, so "
                    f"it renders as a dead column.",
                    field=field_name,
                )
            )

    def _diagnose_unbounded_indexed_string(self, ir: dict[str, Any]) -> None:
        """UNBOUNDED_INDEXED_STRING: an aggregate field that is both included in
        a declared index and an unbounded string.

        A field is unbounded when it is string-typed and carries no bound: IR
        ``type == "Text"`` (unbounded by construction) or ``type == "String"``
        with no ``max_length`` key (the ``String(max_length=None)`` escape
        hatch — a normal ``String()`` defaults to ``max_length=255`` and so is
        bounded). Indexing such a field produces DDL that fails on SQL Server,
        needs a prefix length on MySQL, and is inefficient on PostgreSQL.

        One finding is emitted per flagged field per index occurrence: a field
        in two indexes yields two findings; a composite index over one bounded
        and one unbounded field yields one finding for the unbounded field only.
        """
        abstract_fqns = self._abstract_aggregate_fqns()
        for cluster in ir["clusters"].values():
            aggregate = cluster["aggregate"]
            # Abstract aggregates are non-instantiable bases: they emit no DDL,
            # and their indexes describe a shape no table is built from (the
            # concrete subclass does not carry them). Skip them, matching the
            # other cluster-walking design rules.
            if aggregate["fqn"] in abstract_fqns:
                continue
            for index in aggregate.get("indexes", []):
                # Only ``Index`` entries carry a ``fields`` key; ``RawIndex``
                # entries carry verbatim, opaque DDL and no ``fields``. The
                # missing key is therefore exactly the RawIndex signal, and it
                # also guards the lookup below from raising.
                if "fields" not in index:
                    continue
                self._diagnose_unbounded_index(aggregate, index)

    def _diagnose_unbounded_index(
        self, aggregate: dict[str, Any], index: dict[str, Any]
    ) -> None:
        """Report UNBOUNDED_INDEXED_STRING for each unbounded field in one index."""
        fields = aggregate.get("fields", {})
        index_name = index.get("name", "(unnamed)")

        # A field listed twice within one index is a single occurrence;
        # dedupe (preserving declaration order) so a degenerate
        # ``Index("body", "body")`` yields one finding, not two.
        for field_name in dict.fromkeys(index["fields"]):
            # A field name may reference a value-object or association
            # attribute absent from the scalar fields dict; skip it
            # rather than raise.
            field = fields.get(field_name)
            if field is None:
                continue

            field_type = field.get("type")
            unbounded = field_type == "Text" or (
                field_type == "String" and "max_length" not in field
            )
            if not unbounded:
                continue

            self._diagnostics.append(
                build_diagnostic(
                    DiagnosticCode.UNBOUNDED_INDEXED_STRING,
                    element=aggregate["fqn"],
                    message=f"Field `{field_name}` on aggregate "
                    f"`{aggregate['name']}` is included in index "
                    f"`{index_name}` but is an unbounded string "
                    f"(`{field_type}`). SQL Server rejects indexes "
                    f"on unbounded strings, MySQL requires an "
                    f"explicit prefix length, and PostgreSQL builds "
                    f"the index with storage and performance overhead.",
                    field=field_name,
                    suggestion=f"{field_name} = String(max_length=255)  "
                    f"# size to the field's domain",
                )
            )

    def _diagnose_unindexed_filter_path(self, ir: dict[str, Any]) -> None:
        """Report UNINDEXED_FILTER_PATH for each aggregate field a repository
        query filters on that no declared index covers.

        Reads the ``filter``, ``get``, ``find``, ``find_by`` and ``exclude``
        calls in every registered element's methods. A query whose target
        aggregate :meth:`_resolve_filter_target` cannot resolve is skipped, and
        so is a query on an abstract aggregate. :meth:`_covered_index_fields`
        decides coverage. Only scalar fields are checked, and an operator lookup
        such as ``age__gte`` checks its base field. Emits one diagnostic per
        uncovered field per call-site.
        """
        clusters = ir["clusters"]
        aggregate_fqns = set(clusters.keys())
        abstract_fqns = self._abstract_aggregate_fqns()

        # Repository FQN -> its aggregate FQN, read straight from the clusters
        # the build already assembled. Reading the cluster's ``repositories``
        # section (rather than re-resolving each repository) means only
        # repositories of a real, non-internal cluster are mapped, and the map's
        # values are cluster keys by construction.
        repo_to_aggregate = {
            repo_fqn: agg_fqn
            for agg_fqn, cluster in clusters.items()
            for repo_fqn in cluster["repositories"]
        }

        # Covered-field sets are computed once per target aggregate and reused
        # across all of its call-sites.
        covered_cache: dict[str, set[str]] = {}

        for element_fqn, method_name, call in self._named_field_queries():
            target_fqn = self._resolve_filter_target(
                call.receiver_fqn,
                element_fqn,
                repo_to_aggregate,
                aggregate_fqns,
            )
            # No join target, or an abstract aggregate that builds no
            # table: skip rather than guess (target is a cluster key).
            if target_fqn is None or target_fqn in abstract_fqns:
                continue

            aggregate = clusters[target_fqn]["aggregate"]
            if target_fqn not in covered_cache:
                covered_cache[target_fqn] = self._covered_index_fields(aggregate)

            self._diagnose_unindexed_filter_call(
                aggregate, covered_cache[target_fqn], call, element_fqn, method_name
            )

    def _named_field_queries(self) -> Iterator[tuple[str, str, Any]]:
        """Yield ``(element_fqn, method_name, call)`` for each field-filter query.

        A field-filter query is a repository query call to one of the
        ``FILTER_PATH_QUERY_METHODS`` that names at least one field.
        """
        # Walk every registered (non-internal) element in sorted-FQN order, so
        # the emitted findings are deterministic regardless of registration
        # order. ``element_fqn`` is the enclosing element, used to resolve a
        # self-rooted query written inside a repository.
        for element_fqn, cls in self._registered_elements_by_key():
            for method_name, facts in self.view.element_facts(cls).items():
                for call in facts.calls:
                    if self._is_named_field_query(call):
                        yield element_fqn, method_name, call

    def _registered_elements_by_key(self) -> list[tuple[str, type]]:
        """Return ``(registry key, cls)`` of each non-internal element, key-sorted."""
        registry = self._domain._domain_registry
        elements: list[tuple[str, type]] = []
        for records in registry._elements.values():
            for element_fqn, record in records.items():
                if record.internal:
                    continue
                elements.append((element_fqn, record.cls))
        elements.sort(key=lambda item: item[0])
        return elements

    @staticmethod
    def _is_named_field_query(call: Any) -> bool:
        """Return whether a call is a field-filter repository query."""
        if call.receiver_role is not ReceiverRole.REPOSITORY_QUERY:
            return False
        # A query surface with at least one named field: a persist
        # (``add``) or a dynamic ``filter(**kwargs)`` names none.
        return call.method in FILTER_PATH_QUERY_METHODS and bool(call.field_names)

    def _diagnose_unindexed_filter_call(
        self,
        aggregate: dict[str, Any],
        covered: set[str],
        call: Any,
        element_fqn: str,
        method_name: str,
    ) -> None:
        """Report UNINDEXED_FILTER_PATH for each uncovered field one query names."""
        fields = aggregate.get("fields", {})
        seen: set[str] = set()
        for raw_name in call.field_names:
            # An operator lookup (``age__gte``, ``status__in``)
            # filters its base field; strip the ``__<lookup>`` suffix
            # and evaluate the base, and evaluate each base at most
            # once per call-site (``age__gte`` + ``age__lte`` name the
            # one field ``age``). A real field name never contains a
            # ``__``, so the split is unambiguous.
            field_name = raw_name.split("__", 1)[0]
            if field_name in seen:
                continue
            seen.add(field_name)

            field = fields.get(field_name)
            # Only a real scalar field can be index-covered on its own
            # name; an unknown name, a value-object attribute, or an
            # association names no coverable column and is left alone
            # (conservative, matching the sibling rule's scalar scope).
            if (
                field is None
                or field.get("kind") in NON_SCALAR_FILTER_FIELD_KINDS
                or field_name in covered
            ):
                continue
            self._emit_unindexed_filter_path(
                aggregate,
                field_name,
                element_fqn,
                method_name,
                call.location,
            )

    @staticmethod
    def _covered_index_fields(aggregate: dict[str, Any]) -> set[str]:
        """The fields an aggregate's declared indexes cover for a filter.

        Covered: the identity field (every aggregate IR carries a non-empty
        ``identity_field``), any field carrying a single-column ``unique``
        constraint, and the *leading* column of each ``Index``. ``RawIndex``
        entries carry no ``fields`` key and are skipped; a non-leading composite
        column is deliberately *not* covered, because a filter on it alone
        cannot use the composite index.
        """
        # ``identity_field`` is always present and non-empty for an aggregate
        # (the extractor defaults it to ``"id"``), so it seeds the set directly.
        covered: set[str] = {aggregate["identity_field"]}

        for field_name, field in aggregate.get("fields", {}).items():
            # A field-level ``unique`` constraint is a real index on a relational
            # backend. The identifier never carries this key (the extractor omits
            # it as redundant), so this is only non-PK unique fields.
            if field.get("unique"):
                covered.add(field_name)

        for index in aggregate.get("indexes", []):
            # Only ``Index`` entries carry a ``fields`` key; ``RawIndex`` carries
            # opaque DDL and no fields, and the missing key guards the lookup.
            columns = index.get("fields")
            if columns:
                covered.add(columns[0])

        return covered

    @staticmethod
    def _resolve_filter_target(
        receiver_fqn: str | None,
        element_fqn: str,
        repo_to_aggregate: dict[str, str],
        aggregate_fqns: set[str],
    ) -> str | None:
        """Return the FQN of the aggregate a query call-site filters, or ``None``.

        1. A receiver that resolves to a registered repository gives that
           repository's aggregate.
        2. A receiver that resolves to a registered aggregate gives that
           aggregate.
        3. A self-rooted receiver (``self._dao``, so ``receiver_fqn`` is
           ``None``) inside a repository gives that repository's aggregate.
        4. Anything else gives ``None``.

        A returned FQN is always a key of ``ir["clusters"]``.
        """
        if receiver_fqn is None:
            # Case 3 (repository self-query) or 4: ``get`` returns ``None`` for a
            # self-rooted query written outside a repository.
            return repo_to_aggregate.get(element_fqn)
        if receiver_fqn in repo_to_aggregate:
            return repo_to_aggregate[receiver_fqn]  # case 1
        if receiver_fqn in aggregate_fqns:
            return receiver_fqn  # case 2
        return None  # case 4

    def _emit_unindexed_filter_path(
        self,
        aggregate: dict[str, Any],
        field_name: str,
        source_fqn: str,
        method_name: str,
        location: SourceLocation,
    ) -> None:
        """Append one UNINDEXED_FILTER_PATH finding for a filtered field.

        The call-site is named by the enclosing element's FQN, its method, and
        the source line — all stable across machines. The absolute file path the
        substrate carries is deliberately kept out of the message: diagnostics
        are part of the content-checksummed IR (see
        :data:`~protean.ir.constants.VOLATILE_IR_KEYS`), and an absolute path
        would make a committed baseline machine-specific.
        """
        where = f"{source_fqn}.{method_name}, line {location.line}"
        self._diagnostics.append(
            build_diagnostic(
                DiagnosticCode.UNINDEXED_FILTER_PATH,
                element=aggregate["fqn"],
                message=f"Field `{field_name}` on aggregate `{aggregate['name']}` is "
                f"filtered by `{where}` but no declared index covers it, so "
                f"the query scans the whole table.",
                field=field_name,
                suggestion=f'Index("{field_name}")  # add to `{aggregate["name"]}` indexes',
            )
        )

    def _diagnose_upcaster_gap(self, ir: dict[str, Any]) -> None:
        """UPCASTER_GAP: an event at version N>1 whose stored predecessors have
        no upcaster path to N (build-time signal for a read-time failure).

        Reads the registry because an event's ``abstract`` flag is not
        projected into the IR. A malformed chain (duplicate/cyclic/non-convergent)
        is already an error that preempts IR building, so this only reaches the
        two silent cases: no upcasters at all, or partial coverage of ``1..N-1``.
        """
        registry = self._domain._domain_registry

        # (from_version, to_version) edges per event, keyed by bare name so a
        # string event_type resolves the same way build_chains does. Two events
        # sharing a class name across aggregates would pool edges, a
        # limitation of the name-based type string.
        # TODO(#1985): key by the event's qualified name.
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
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.UPCASTER_GAP,
                        element=fqn(event_cls),
                        message=f"Event `{event_cls.__name__}` is at version "
                        f"{current_version}; stored payloads at {versions}, if "
                        f"any exist, have no upcaster path to "
                        f"v{current_version} and would fail to deserialize. "
                        f"Add upcasters covering the missing versions.",
                    )
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
                self._diagnose_cross_references_in(
                    element_fqn, fields, own, cluster_keys
                )

    def _diagnose_cross_references_in(
        self,
        element_fqn: str,
        fields: dict[str, Any],
        own: str,
        cluster_keys: set[str],
    ) -> None:
        """Report CROSS_AGGREGATE_REFERENCE for each field of one element that
        references another cluster's root."""
        for field_name, field in fields.items():
            if field.get("kind") != "reference":
                continue
            if field.get("auto_generated"):
                continue
            target = field.get("target")
            if target in cluster_keys and target != own:
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.CROSS_AGGREGATE_REFERENCE,
                        element=element_fqn,
                        message=f"Reference `{field_name}` points at a "
                        f"different aggregate's root `{target}`; "
                        f"aggregates should reference each other by "
                        f"identity, not by `Reference`.",
                        field=field_name,
                    )
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
                    build_diagnostic(
                        DiagnosticCode.ES_AGGREGATE_NO_EVENTS,
                        element=aggregate["fqn"],
                        message=f"Event-sourced aggregate `{aggregate['name']}` has "
                        f"no events; it records no state changes and cannot "
                        f"be rebuilt from its stream.",
                    )
                )

    def _diagnose_handler_persists_and_calls_out(self, ir: dict[str, Any]) -> None:
        """Report HANDLER_PERSISTS_AND_CALLS_OUT for each handler method that
        calls a known I/O library after its first ``repository_for(...)`` call.

        Scans event handlers, command handlers, projectors and process managers.
        Both calls must resolve statically, and only the method's own body is
        read. See ADR-0031.
        """
        # Process managers are included: they run their own dispatch loop, but
        # it wraps each method in a UnitOfWork too, so the hazard is identical.
        # (ADR-0031 defers process managers on *sibling failure isolation*, a
        # state-transition question. This rule is about transaction boundaries,
        # which has no process-manager-specific semantics.)
        handler_types = (
            "EVENT_HANDLER",
            "COMMAND_HANDLER",
            "PROJECTOR",
            "PROCESS_MANAGER",
        )

        # `_elements[<type>]` is already keyed by fqn, and a class lands in
        # exactly one bucket, so no dedupe is needed. Sorted for a stable
        # diagnostic order.
        registry = self._domain._domain_registry
        scanned = sorted(
            (element_fqn, record.cls)
            for element_type in handler_types
            for element_fqn, record in registry._elements.get(element_type, {}).items()
            if not record.internal
        )

        for element_fqn, cls in scanned:
            for method_name, facts in self.view.element_facts(cls).items():
                io = self._io_call_after_persist(facts)
                if io is None:
                    continue
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.HANDLER_PERSISTS_AND_CALLS_OUT,
                        element=element_fqn,
                        message=f"Handler `{cls.__name__}` method "
                        f"`{method_name}` persists, then calls "
                        f"`{io.callee_fqn}` (line {io.location.line}), which "
                        f"can hold the transaction open across the call.",
                    )
                )

    @staticmethod
    def _io_call_after_persist(facts: Any) -> Any | None:
        """Return a method's first I/O call after its first persistence call.

        Returns ``None`` when the method makes no persistence call, or no I/O
        call after it.
        """
        # `(line, col)` so a persist and an I/O call on the same physical
        # line still order correctly.
        persist_pos = min(
            (
                (call.location.line, call.location.col)
                for call in facts.calls
                if is_persistence_call(call.callee_fqn)
            ),
            default=None,
        )
        if persist_pos is None:
            return None
        # Only an I/O call after the first repository access can be
        # inside the transaction; one before it runs outside.
        return next(
            (
                call
                for call in facts.calls
                if (call.location.line, call.location.col) > persist_pos
                and is_external_io_call(call.callee_fqn)
            ),
            None,
        )

    def _diagnose_unraised_event(self, ir: dict[str, Any]) -> None:
        """Report UNRAISED_EVENT for each cluster event that no method of the
        cluster's aggregate or entity classes raises.

        A method raises an event when it both calls ``raise_`` and constructs
        the event. Skips fact events, auto-generated events, clusters whose
        aggregate is abstract, and clusters none of whose classes resolve to
        indexed source. Published events are checked.
        """
        abstract_fqns = self._abstract_aggregate_fqns()

        # Cluster IR carries FQNs, not class objects. Map each aggregate/entity
        # FQN back to its class through the registry so the view can be asked for
        # its facts and class entry.
        registry = self._domain._domain_registry
        cls_by_fqn: dict[str, type] = {}
        for element_type in ("AGGREGATE", "ENTITY"):
            for record in registry._elements.get(element_type, {}).values():
                cls_by_fqn[fqn(record.cls)] = record.cls

        for _cluster_fqn, cluster in sorted(ir["clusters"].items()):
            if cluster["aggregate"]["fqn"] in abstract_fqns:
                continue

            class_fqns = [cluster["aggregate"]["fqn"], *cluster["entities"].keys()]
            classes = [cls_by_fqn[f] for f in class_fqns if f in cls_by_fqn]

            # Fail open on the class entry: analyze the cluster only when at least
            # one of its classes resolves to indexed source.
            analyzed = [
                cls for cls in classes if self.view.element_class_entry(cls) is not None
            ]
            if not analyzed:
                continue

            raised_fqns = self._raised_event_fqns(analyzed)
            self._emit_unraised_events(cluster, raised_fqns)

    def _raised_event_fqns(self, classes: list[type]) -> set[str]:
        """Return the FQNs constructed in any method of ``classes`` that raises."""
        # An event is raised when a single method both calls `raise_` and
        # constructs it. Correlate at the method level, not the argument span.
        # Match on the method name: the factory idiom
        # `user.raise_(Registered(...))` leaves the receiver role UNKNOWN.
        raised_fqns: set[str] = set()
        for cls in classes:
            for facts in self.view.element_facts(cls).values():
                if not any(call.method == RAISE_METHOD for call in facts.calls):
                    continue
                for construction in facts.constructions:
                    raised_fqns.add(construction.fqn)
        return raised_fqns

    def _emit_unraised_events(
        self, cluster: dict[str, Any], raised_fqns: set[str]
    ) -> None:
        """Report UNRAISED_EVENT for each checked cluster event not in ``raised_fqns``."""
        for _event_fqn, event in sorted(cluster["events"].items()):
            if event.get("is_fact_event", False) or event.get("auto_generated", False):
                continue
            if event["fqn"] in raised_fqns:
                continue
            self._diagnostics.append(
                build_diagnostic(
                    DiagnosticCode.UNRAISED_EVENT,
                    element=event["fqn"],
                    message=f"Event {event['name']} is raised by no "
                    f"aggregate or entity method",
                )
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
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.QUERY_HANDLER_WITHOUT_QUERY,
                        element=projection["fqn"],
                        message=f"Projection `{projection['name']}` has a query "
                        f"handler but no query to serve",
                    )
                )

    def _diagnose_value_object_mutable_field(self, ir: dict[str, Any]) -> None:
        """VALUE_OBJECT_MUTABLE_FIELD: a value object with a ``list``/``dict``
        field, which gives it mutable state and breaks equality-by-value.

        Only value objects reachable from a (non-abstract) aggregate cluster are
        checked: a VO an aggregate, an entity, a command or an event holds in a
        field, or one that carries ``part_of``.
        Emits one finding per offending field, naming it in the optional
        ``field`` key (mirroring ``DEPRECATED_FIELD``).
        """
        abstract_fqns = self._abstract_aggregate_fqns()
        for cluster in ir["clusters"].values():
            if cluster["aggregate"]["fqn"] in abstract_fqns:
                continue
            for vo in cluster["value_objects"].values():
                for field_name, field in vo["fields"].items():
                    if field.get("kind") not in ("list", "dict"):
                        continue
                    self._diagnostics.append(
                        build_diagnostic(
                            DiagnosticCode.VALUE_OBJECT_MUTABLE_FIELD,
                            element=vo["fqn"],
                            message=f"Value object `{vo['name']}` has mutable field "
                            f"`{field_name}` (`{field['kind']}`); value "
                            f"objects must be immutable.",
                            field=field_name,
                        )
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
                        self._diagnostics.append(
                            build_diagnostic(
                                DiagnosticCode.PROJECTOR_HANDLES_ORPHANED_EVENT,
                                element=projector["fqn"],
                                message=f"Projector `{projector['name']}` handles "
                                f"event `{event_type}` which the domain does "
                                f"not register",
                            )
                        )

    def _diagnose_command_handler_cross_cluster(self, ir: dict[str, Any]) -> None:
        """COMMAND_HANDLER_CROSS_CLUSTER: handler processing another cluster's command.

        A command handler in cluster A that handles a command owned by cluster
        B crosses an aggregate boundary — the write path for B's command lives
        outside B's cluster. Commands registered in *no* cluster are out of
        scope (they cannot be attributed to an owner), and same-cluster commands
        are the expected case. Only commands are considered — event handlers may
        legitimately react across clusters.
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
                        self._diagnostics.append(
                            build_diagnostic(
                                DiagnosticCode.COMMAND_HANDLER_CROSS_CLUSTER,
                                element=ch["fqn"],
                                message=f"Command handler `{ch['name']}` in cluster "
                                f"`{agg_fqn}` handles command `{command_type}` "
                                f"owned by cluster `{owner}`",
                            )
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
                    build_diagnostic(
                        DiagnosticCode.AGGREGATE_TOO_LARGE,
                        element=aggregate["fqn"],
                        message=f"Aggregate `{aggregate['name']}` has {entity_count} "
                        f"entities (limit: {limit})",
                    )
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
                        build_diagnostic(
                            DiagnosticCode.HANDLER_TOO_BROAD,
                            element=ch["fqn"],
                            message=f"Handler `{ch['name']}` handles {handler_count} "
                            f"message types (limit: {limit})",
                        )
                    )
            # Check event handlers
            for eh in cluster["event_handlers"].values():
                handler_count = len(eh.get("handlers", {}))
                if handler_count > limit:
                    self._diagnostics.append(
                        build_diagnostic(
                            DiagnosticCode.HANDLER_TOO_BROAD,
                            element=eh["fqn"],
                            message=f"Handler `{eh['name']}` handles {handler_count} "
                            f"message types (limit: {limit})",
                        )
                    )

    def _diagnose_event_without_data(self, ir: dict[str, Any]) -> None:
        """EVENT_WITHOUT_DATA: event with zero user-defined fields.

        An event with no fields carries no information beyond its type name.
        This is usually a mistake — events should capture the relevant state
        change data.  Auto-generated fields (id, _metadata) are excluded.
        """
        for cluster in ir["clusters"].values():
            for event in cluster["events"].values():
                # Skip fact events and auto-generated events
                if event.get("is_fact_event", False):
                    continue
                if event.get("auto_generated", False):
                    continue
                if not self._event_user_fields(event):
                    self._diagnostics.append(
                        build_diagnostic(
                            DiagnosticCode.EVENT_WITHOUT_DATA,
                            element=event["fqn"],
                            message=f"Event `{event['name']}` has no user-defined fields",
                        )
                    )

    @staticmethod
    def _event_user_fields(event: dict[str, Any]) -> set[str]:
        """Return an event's field names other than ``id`` and ``_metadata``."""
        auto_field_names = {"id", "_metadata"}
        return {
            name for name in event.get("fields", {}) if name not in auto_field_names
        }

    def _diagnose_subscriber_no_streams(self, ir: dict[str, Any]) -> None:
        """SUBSCRIBER_NO_STREAMS: subscriber with no stream to consume.

        A subscriber whose ``stream`` is empty or unset has nothing to
        subscribe to, so it will never be invoked.
        """
        for sub in ir["flows"]["subscribers"].values():
            if not sub.get("stream"):
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.SUBSCRIBER_NO_STREAMS,
                        element=sub["fqn"],
                        message=f"Subscriber `{sub['name']}` declares no stream to consume",
                    )
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
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.PROCESS_MANAGER_UNCLOSED,
                        element=pm["fqn"],
                        message=f"Process manager `{pm['name']}` has no handler "
                        f"marked `end=True` to close its instances",
                    )
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
            self._diagnostics.append(
                build_diagnostic(
                    DiagnosticCode.DEPRECATED_ELEMENT,
                    element=fqn_val,
                    message=self._element_deprecation_message(
                        name, deprecated, element.get("superseded_by")
                    ),
                )
            )

        # Field-level deprecation (independent of element deprecation)
        for field_name, field_info in element.get("fields", {}).items():
            self._check_field_deprecated(name, fqn_val, field_name, field_info)

        # Option-level deprecation (currently only commands passed the event-only
        # ``published`` option). Warning-level: unlike a still-functional
        # deprecated element, the option is inert today and becomes a hard
        # ``IncorrectUsageError`` at its removal version.
        published_removal = DEPRECATIONS["command_published_option"].removal
        for opt in element.get("deprecated_options", []):
            self._diagnostics.append(
                build_diagnostic(
                    DiagnosticCode.DEPRECATED_OPTION,
                    element=fqn_val,
                    message=f"The `{opt}` option on `{name}` is deprecated and "
                    f"scheduled for removal in v{published_removal}; commands are internal "
                    f"to the bounded context and carry no published-language "
                    f"or fact-event semantics, so it has no effect.",
                    level="warning",
                    rationale="The option is inert today and becomes a hard "
                    f"IncorrectUsageError at v{published_removal}.",
                    fix=f"Remove the `{opt}` option from `{name}`; it has no effect.",
                )
            )

    @staticmethod
    def _element_deprecation_message(
        name: str, deprecated: dict[str, Any], superseded_by: Any
    ) -> str:
        """Return the DEPRECATED_ELEMENT message for one element."""
        since = deprecated.get("since", "?")
        removal = deprecated.get("removal")
        if removal:
            msg = (
                f"`{name}` is deprecated since v{since}, "
                f"scheduled for removal in v{removal}"
            )
        else:
            msg = f"`{name}` is deprecated since v{since}"

        if superseded_by:
            msg += f"; superseded by `{superseded_by}`"
        return msg

    def _check_field_deprecated(
        self, name: str, fqn_val: str, field_name: str, field_info: dict[str, Any]
    ) -> None:
        """Emit DEPRECATED_FIELD diagnostics for one field of an element."""
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
                f_msg = f"Field `{name}.{field_name}` is deprecated since v{f_since}"
            self._diagnostics.append(
                build_diagnostic(
                    DiagnosticCode.DEPRECATED_FIELD,
                    element=fqn_val,
                    message=f_msg,
                    field=field_name,
                )
            )

        # Deprecated ``pickled=`` argument on a ``List`` field. The argument
        # is inert (it never had an effect); this only nudges the user to
        # drop it before the removal version.
        if field_info.get("deprecated_pickled"):
            p_removal = DEPRECATIONS["list_pickled"].removal
            self._diagnostics.append(
                build_diagnostic(
                    DiagnosticCode.DEPRECATED_FIELD,
                    element=fqn_val,
                    message=f"Field `{name}.{field_name}` uses the deprecated "
                    f"`pickled=` argument on `List`, scheduled for removal "
                    f"in v{p_removal}; it has no effect.",
                    field=field_name,
                    rationale="The `pickled` argument on `List` is a dead legacy flag "
                    "with no effect; it is scheduled for removal.",
                    fix=f"Remove the `pickled=` argument from `{name}.{field_name}`; "
                    f"it has no effect.",
                )
            )

    def _diagnose_deprecated_options(self, ir: dict[str, Any]) -> None:
        """DEPRECATED_OPTION: a deprecated decorator/register option was used.

        Reads the aggregate registry (the deprecated-option marker is not
        projected into the IR, keeping the IR wire format unchanged) and emits
        an INFO-level diagnostic per aggregate that used a deprecated option
        alias, e.g. ``is_event_sourced=`` instead of ``event_sourced=``.
        """
        registry = self._domain._domain_registry
        removal = DEPRECATIONS["is_event_sourced_alias"].removal
        for record in registry._elements.get("AGGREGATE", {}).values():
            # Read the class's own attribute (not an inherited one) so a
            # subclass of an alias-using aggregate is not wrongly flagged.
            used = record.cls.__dict__.get("_deprecated_options_used", ())
            for option in used:
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.DEPRECATED_OPTION,
                        element=fqn(record.cls),
                        message=f"Option `{option}` is deprecated, scheduled for "
                        f"removal in v{removal}; use `event_sourced` instead.",
                    )
                )

    def _diagnose_deprecated_imports(self, ir: dict[str, Any]) -> None:
        """Report DEPRECATED_IMPORT for each deprecated import surface used in a
        module that hosts a registered element.

        :meth:`_find_deprecated_import_uses` defines the surfaces. Runs by
        default. Emits one diagnostic per ``(module, symbol)``, attributed to
        the module. A module that cannot be read or parsed is skipped.
        """
        removal = DEPRECATIONS["method_field"].removal  # all three share one version

        for module in self._element_modules():
            tree = self.source.tree(module)
            uses = self._find_deprecated_import_uses(tree) if tree is not None else []
            for kind, symbol in uses:
                message, fix = self._deprecated_import_text(kind, symbol, removal)
                self._diagnostics.append(
                    build_diagnostic(
                        DiagnosticCode.DEPRECATED_IMPORT,
                        element=module,
                        message=message,
                        fix=fix,
                    )
                )

    def _element_modules(self) -> list[str]:
        """Return the sorted modules that host a non-internal registered element."""
        # A module-level import is one fact regardless of how many elements
        # live in the module, so dedupe on the module here.
        registry = self._domain._domain_registry
        modules: set[str] = set()
        for records in registry._elements.values():
            for record in records.values():
                if record.internal:
                    continue
                module = getattr(record.cls, "__module__", None)
                if module:
                    modules.add(module)
        return sorted(modules)

    @staticmethod
    def _deprecated_import_text(
        kind: str, symbol: str, removal: str | None
    ) -> tuple[str, str]:
        """Return the DEPRECATED_IMPORT ``(message, fix)`` for one use."""
        if kind == "field":
            message = (
                f"`{symbol}` is a deprecated serializer field type, "
                f"scheduled for removal in v{removal}. Serializer fields "
                f"are no longer supported."
            )
            fix = f"Remove the `{symbol}` field; serializer fields are gone."
        else:  # "util"
            message = (
                f"`{symbol}` is deprecated internal plumbing, scheduled "
                f"for removal in v{removal}. It has no public replacement."
            )
            fix = f"Stop importing `{symbol}`; it is internal plumbing."
        return message, fix

    @staticmethod
    def _find_deprecated_import_uses(tree: ast.Module) -> list[tuple[str, str]]:
        """Return a ``(kind, symbol)`` pair, in a deterministic order, for each
        deprecated import surface used in ``tree``.

        - ``"field"``: a ``Method`` or ``Nested`` call through a name bound by
          a module-level ``from protean.fields import ...`` or
          ``from protean.fields.basic import ...``, or through either module
          as an attribute. A name imported inside a function is not matched,
          and an import with no call is not matched.
        - ``"util"``: a deprecated ``protean.utils`` name, imported by name or
          reached as an attribute, at any scope.

        A whole-module alias (``import protean.fields as pf``) matches the same
        as the full module name.
        """
        return _DeprecatedImportScan(tree)._uses()

    def _diagnose_aggregate_no_invariants(self, ir: dict[str, Any]) -> None:
        """AGGREGATE_NO_INVARIANTS: an aggregate with no pre/post invariants,
        usually an anemic data holder rather than a true consistency boundary.
        INFO-level design nudge, not a build failure.

        ``abstract`` is not projected into the aggregate IR ``options`` block, so
        it is sourced from the registry (mirroring ``_diagnose_upcaster_gap``).
        Internal and abstract aggregates are skipped. ``invariants`` is the dict
        ``{"pre": [...], "post": [...]}``; flag only when *both* lists are empty.
        """
        registry = self._domain._domain_registry
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
                    build_diagnostic(
                        DiagnosticCode.AGGREGATE_NO_INVARIANTS,
                        element=agg_fqn,
                        message=f"Aggregate `{record.cls.__name__}` has no pre/post "
                        f"invariants (own or inherited); it enforces no "
                        f"business rules and may be an anemic data holder.",
                    )
                )

    def _diagnose_event_not_past_tense(self, ir: dict[str, Any]) -> None:
        """EVENT_NOT_PAST_TENSE: domain event named as a gerund, not past tense.

        Advisory (info-level) naming check. A domain event records a fact that
        has already happened, so it reads best in the past tense
        (``OrderPlaced``). A gerund name (``OrderPlacing``) describes an
        in-flight action and reads like a command. Framework-managed events —
        fact events and auto-generated process-manager events — are not
        user-named and are skipped.
        """
        for cluster in ir["clusters"].values():
            for event in cluster["events"].values():
                # Framework-managed events (fact events, PM-generated events)
                # are not user-named — skip them.
                if event.get("is_fact_event", False) or event.get(
                    "auto_generated", False
                ):
                    continue
                if event["name"].lower().endswith("ing"):
                    self._diagnostics.append(
                        build_diagnostic(
                            DiagnosticCode.EVENT_NOT_PAST_TENSE,
                            element=event["fqn"],
                            message=f"Event `{event['name']}` is named as a gerund; "
                            f"domain events read best in the past tense",
                        )
                    )

    def _diagnose_command_not_imperative(self, ir: dict[str, Any]) -> None:
        """COMMAND_NOT_IMPERATIVE: command not named as an imperative verb phrase.

        Advisory (info-level) naming check. A command expresses an intent to
        act, so it reads best as an imperative verb phrase (``PlaceOrder``). A
        name that does not begin with a known imperative verb (``OrderCreation``,
        ``OrderCommand``) reads like a noun or an event. The prefix match is
        case-insensitive and requires a CamelCase token boundary right after
        the verb, so ``AddressChange`` is not mistaken for ``Add``-prefixed
        (``AddItem``). Verbs listed in ``[lint].command_verbs`` are accepted
        alongside :data:`IMPERATIVE_VERBS`, under the same rules.
        """
        project_verbs = self._domain.config.get("lint", {}).get("command_verbs", [])
        verbs = IMPERATIVE_VERBS | {verb.lower() for verb in project_verbs}
        for cluster in ir["clusters"].values():
            for command in cluster["commands"].values():
                raw_name = command["name"]
                name = raw_name.lower()
                if not any(
                    name.startswith(verb)
                    and (len(raw_name) == len(verb) or raw_name[len(verb)].isupper())
                    for verb in verbs
                ):
                    self._diagnostics.append(
                        build_diagnostic(
                            DiagnosticCode.COMMAND_NOT_IMPERATIVE,
                            element=command["fqn"],
                            message=f"Command `{command['name']}` does not start "
                            f"with an imperative verb; commands read best "
                            f"as verb-first phrases",
                        )
                    )

    def _diagnose_aggregate_not_noun(self, ir: dict[str, Any]) -> None:
        """AGGREGATE_NOT_NOUN: aggregate named as a verb, gerund, or adjective.

        Advisory (info-level) naming check. An aggregate models a *thing* in
        the domain, so it reads best as a noun (``Order``, ``Customer``). A
        gerund, verb, or adjective name (``OrderProcessing``, ``Notify``,
        ``Recursive``) reads like a process or a capability rather than a
        concept. Agent nouns legitimately end in ``-er``/``-or``/``-ator``
        (``Customer``, ``Auditor``) and are *not* flagged. Infrastructure
        aggregates under ``protean.adapters.`` are skipped.
        """
        for cluster in ir["clusters"].values():
            aggregate = cluster["aggregate"]
            # Skip infrastructure aggregates
            if aggregate["fqn"].startswith("protean.adapters."):
                continue
            name = aggregate["name"]
            lowered = name.lower()
            for suffix in NON_NOUN_AGGREGATE_SUFFIXES:
                # Length guard: a name equal to a suffix must not self-match.
                if lowered.endswith(suffix) and len(name) > len(suffix):
                    self._diagnostics.append(
                        build_diagnostic(
                            DiagnosticCode.AGGREGATE_NOT_NOUN,
                            element=aggregate["fqn"],
                            message=f"Aggregate `{name}` is named as a verb, "
                            f"gerund, or adjective; aggregates read best "
                            f"as nouns",
                        )
                    )
                    break

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
            results = self._custom_rule_results(path, ir, logger)
            if results is None:
                continue
            for item in results:
                if not self._is_valid_custom_item(path, item, logger):
                    continue
                # Custom findings default to the ``custom`` category so they
                # carry the same schema shape as built-in diagnostics; the
                # forward-compat ``rule``/``suggestion`` keys stay optional.
                item.setdefault("category", "custom")
                self._diagnostics.append(item)

    def _custom_rule_results(
        self, path: str, ir: dict[str, Any], logger: logging.Logger
    ) -> list[Any] | None:
        """Import and run one custom lint rule.

        Returns the rule's result list, or ``None`` after logging a warning
        when the rule cannot be imported, raises, or returns a non-list.
        """
        try:
            callable_fn = self._import_callable(path)
        except Exception as exc:  # noqa: BLE001 - importing a rule runs user code
            logger.warning(
                "Custom lint rule %r could not be imported (%r), skipped",
                path,
                exc,
            )
            return None

        try:
            results = callable_fn(ir)
        except Exception as exc:  # noqa: BLE001 - a rule is user code
            logger.warning("Custom lint rule %r raised %r, skipped", path, exc)
            return None

        if not isinstance(results, list):
            logger.warning(
                "Custom lint rule %r returned %s instead of a list, so it was skipped",
                path,
                type(results).__name__,
            )
            return None
        return results

    def _is_valid_custom_item(
        self, path: str, item: Any, logger: logging.Logger
    ) -> bool:
        """Return whether one custom rule result is a well-formed diagnostic.

        Logs a warning for a result that is not.
        """
        if not isinstance(item, dict):
            logger.warning(
                "Custom lint rule %r returned a non-dict item, so it was skipped",
                path,
            )
            return False
        missing = self._REQUIRED_KEYS - set(item)
        if missing:
            logger.warning(
                "Custom lint rule %r returned item missing keys %s, so it was skipped",
                path,
                missing,
            )
            return False
        if item["level"] not in self._VALID_LEVELS:
            logger.warning(
                "Custom lint rule %r returned invalid level %r, so it was skipped",
                path,
                item["level"],
            )
            return False
        return True

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

        Also strips ``teaching_skills`` from each diagnostic before hashing. That
        key names the DX-pack skills that teach a code, so it is present or absent
        with the pack, not with the domain. Hashing it would make the same domain
        check STALE when the pack is stripped (a CI runner without the pack, or
        an upgrade from a version that never emitted the key), so it stays out of
        the digest. ``ir diff`` already ignores it: diagnostics are matched by
        ``(code, element)`` and their inner fields are not compared.
        """
        ir_copy = {k: v for k, v in ir.items() if k not in VOLATILE_IR_KEYS}
        diagnostics = ir_copy.get("diagnostics")
        if isinstance(diagnostics, list):
            ir_copy["diagnostics"] = [
                {k: v for k, v in diag.items() if k != "teaching_skills"}
                if isinstance(diag, dict)
                else diag
                for diag in diagnostics
            ]
        canonical = json.dumps(ir_copy, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"
