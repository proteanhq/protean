"""Behavioral facts inside a method body, over a domain's parsed sources.

:class:`FactCatalog` is the fourth layer of the ``protean check`` behavioral
substrate. The three below it turn a domain into parsed trees
(:class:`~protean.ir.analysis.source_provider.SourceProvider`), a class/method
index (:class:`~protean.ir.analysis.element_index.ElementIndex`), and a name
resolver (:class:`~protean.ir.analysis.symbols.SymbolResolver`). This one reads
a single method body and reports the three fact kinds a behavioral rule needs:

- **call facts** — a call site, with the callee's FQN (where it resolves), the
  keyword field names it passes, and the Protean role of the object it is
  called on (repository query, ``raise_``, Unit of Work, or unknown);
- **attribute facts** — an attribute read or an attribute write
  (``self.total`` versus ``self.status = "x"``), told apart by the ctx the
  grammar gives the node;
- **construction facts** — a call whose callee resolves to a registered domain
  element (``Order(...)``), which is what lets a rule see an aggregate being
  built.

Internal API. Nothing here is re-exported from ``protean`` or ``protean.ir``.

Scope is this method's own body
-------------------------------
The walk descends through every expression of the method body — a call nests in
an argument, a comprehension, an f-string, a boolean chain — because a call-only
statement walk would miss most of them. It stops at a nested ``def``, ``async
def``, ``lambda`` or ``class`` scope: a call written inside a nested function is
a fact of *that* function, not of the method that encloses it, mirroring the
element index's rule that a method of a nested class is not a method of the
outer one. That stop is whole-node, so a nested callable's own signature
(default argument values, decorators, annotations) is dropped with its body,
even though those expressions run in this method's frame — a rare
``def inner(x=self.repo.find()): ...`` loses the ``self.repo.find()`` fact. A
comprehension does not open such a boundary here — its calls are lexically part
of the method's logic — so the walk descends into it. The method's own signature
(decorators, default argument values, annotations) is not walked either: those
execute in the enclosing class body, not in this method.

A call is a construction, or it is a call — not both
----------------------------------------------------
A call whose resolved callee names a registered domain element is recorded as a
:class:`ConstructionFact` and nothing else; every other call is a
:class:`CallFact`. The two never overlap: a construction is a bare-name or
dotted-name call on the element itself (no receiver to give a role), and a call
fact is a method invoked on a receiver. Recording a construction as both would
force every consumer to dedupe.

Read versus write is the ctx the grammar gives
----------------------------------------------
``ast.Attribute.ctx`` is ``Store`` for ``self.status = "x"`` and for the target
of an augmented assignment (``self.count += 1``), ``Del`` for ``del self.x``,
and ``Load`` for a plain read. A write is ``Store`` or ``Del``; everything else
is a read. An augmented assignment reads as well as writes, but the grammar
models its target as a single store node, so it is recorded as a write — which
is the half a lost-write rule keys on. The attribute that names the method of a
call (``self._dao.filter`` — the ``filter``) is *not* a data access and yields
no attribute fact; the receiver it is loaded from (``self._dao``) still does.

Two mutations the ctx does *not* surface as a ``self.*`` write, because Python
loads the outer attribute in both: a subscripted write (``self.items[0] = 5``
stores into the subscript, so ``items`` is a *read*) and a nested-attribute
write (``self.a.b = 1`` writes ``b`` with no plain-name receiver, and reads
``a``). Faithful to the grammar, but a mutation-of-``self`` rule built on this
must know a write to ``self.items[0]`` or ``self.a.b`` shows here as a read of
the container, not a write of it.

Receiver-role resolution is conservative
-----------------------------------------
A call's receiver is classified into a Protean role only when it is statically
recognizable — ``self``, a name or attribute chain rooted at ``self`` or at a
module-level name the resolver knows, or a construction. A receiver rooted at a
plain local variable (``repo = ...; repo.filter(...)``) needs dataflow to know
what it holds, which is a later layer (#1223); until then it is left
:attr:`ReceiverRole.UNKNOWN` rather than guessed. Recognition is by the known
method-name surface plus a recognizable receiver, never by proving a receiver
"is a repository" by type — that is what keeps every verdict reproducible. The
cost is precision, not soundness: a self-rooted call to a method that happens to
share a name with the repository surface (``self.items.add(...)``) is tagged
``REPOSITORY_QUERY`` here, and a later layer with type or dataflow information
narrows it.

Skip, never guess
-----------------
A ``**kwargs`` double-star in a call marks the call as having dynamic keywords
and contributes no field name — a fabricated ``status`` feeds a downstream false
positive and a miss does not. A field name reached only through ``getattr`` or a
computed string is likewise absent. A ``Q(field=...)`` written inline in a query
call contributes ``field``; a ``Q`` held in a variable, or one composed with
``&``/``|``, is not statically a field set and contributes nothing.

Contracts
---------
- **Fail open.** A method whose module has no source, or a node the resolver
  cannot place, yields empty facts, never a raise.
- **Analysis is of source as written.** Facts are read from the AST, not from
  what would run, which is what makes them reproducible.
- **Deterministic.** Facts are emitted in source order and the public accessors
  sort them by ``(line, col)``, so two catalogs over the same source produce the
  same facts in the same order.
- **Single-threaded.** One catalog per build, sharing that build's provider,
  index, and resolver; give each thread its own, as with the other layers.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from protean.ir.analysis.element_index import ElementIndex, FunctionNode
from protean.ir.analysis.source_provider import SourceProvider
from protean.ir.analysis.symbols import SymbolResolver

if TYPE_CHECKING:
    from protean.domain import Domain

#: The FQN of a repository/DAO query method the receiver-role rule recognizes.
#: ``add``/``get`` are the repository surface (``repository.py``), ``find``/
#: ``find_by`` its query helpers, ``filter``/``exclude`` the ``QuerySet``
#: surface (``queryset.py``). Matching is by this name plus a recognizable
#: receiver, never by the receiver's type.
_QUERY_METHODS = frozenset({"add", "get", "find_by", "find", "filter", "exclude"})

#: The method name Protean raises a domain event through (``self.raise_(...)``,
#: on both aggregates and entities).
_RAISE_METHOD = "raise_"

#: The FQN of the Unit of Work, so a call on a recognizable Unit-of-Work
#: receiver is tagged even before dataflow lands.
_UNIT_OF_WORK_FQN = "protean.core.unit_of_work.UnitOfWork"

#: The FQN of ``Q``, whose inline ``Q(field=...)`` form names query fields.
_Q_FQN = "protean.utils.query.Q"

#: Scopes the method-body walk does not descend into: a call inside one of these
#: is a fact of that nested callable, not of the method enclosing it.
_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


class ReceiverRole(StrEnum):
    """The Protean role of the object a call is made on.

    A call carries exactly one role. :attr:`UNKNOWN` is the single "not
    statically determinable" answer: a receiver that is a plain local variable,
    a computed expression, or a recognizable receiver whose method names none of
    the known surfaces.
    """

    REPOSITORY_QUERY = "REPOSITORY_QUERY"
    RAISE_ = "RAISE_"
    UNIT_OF_WORK = "UNIT_OF_WORK"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Where a fact is, as ``path:line:col``.

    ``path`` is the file the tree was read from, or ``None`` when the provider
    has no origin for the module. ``line`` and ``col`` are the node's own
    1-based line and 0-based column, straight from the AST.
    """

    path: str | None
    line: int
    col: int


@dataclass(frozen=True, slots=True)
class CallFact:
    """A call site that is not a domain-element construction."""

    #: The callee's fully-qualified name, or ``None`` where it does not resolve
    #: (a method on a receiver whose root is not a resolvable name).
    callee_fqn: str | None
    #: The trailing name of the callee — the method name for ``x.method(...)``,
    #: the function name for ``func(...)`` — or ``None`` for a computed callee.
    method: str | None
    #: The FQN the receiver resolves to, or ``None``. Present only when the
    #: whole receiver chain resolves; ``self``-rooted receivers do not.
    receiver_fqn: str | None
    #: The Protean role of the receiver.
    receiver_role: ReceiverRole
    #: The keyword field names the call passes, in source order, plus any names
    #: from an inline ``Q(field=...)`` in a query call. A ``**kwargs`` star
    #: contributes none.
    field_names: tuple[str, ...]
    #: Whether the call passes a ``**kwargs`` double-star, so a consumer knows
    #: the field set is not exhaustive.
    dynamic_kwargs: bool
    location: SourceLocation

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<CallFact {self.method} line {self.location.line}>"


@dataclass(frozen=True, slots=True)
class AttributeFact:
    """An attribute read or write on some receiver."""

    #: The attribute name (``status`` for ``self.status``).
    name: str
    #: The receiver's name when it is a plain name (``self`` for ``self.x``), or
    #: ``None`` when the receiver is a more complex expression.
    receiver: str | None
    #: ``True`` for a store or delete, ``False`` for a load.
    is_write: bool
    location: SourceLocation

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        kind = "write" if self.is_write else "read"
        return f"<AttributeFact {self.name} {kind} line {self.location.line}>"


@dataclass(frozen=True, slots=True)
class ConstructionFact:
    """A call whose callee resolves to a registered domain element."""

    #: The constructed element's fully-qualified name.
    fqn: str
    #: The keyword field names passed to the constructor, in source order.
    field_names: tuple[str, ...]
    #: Whether the construction passes a ``**kwargs`` double-star.
    dynamic_kwargs: bool
    location: SourceLocation

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ConstructionFact {self.fqn} line {self.location.line}>"


@dataclass(frozen=True, slots=True)
class MethodFacts:
    """Every fact of one method body, split by kind.

    Each tuple is sorted by ``(line, col)``, so two catalogs over the same
    source produce the same facts in the same order.
    """

    calls: tuple[CallFact, ...]
    attributes: tuple[AttributeFact, ...]
    constructions: tuple[ConstructionFact, ...]


#: The empty result a fail-open path returns, shared so every such path returns
#: an equal (and cheap) value.
_NO_FACTS = MethodFacts((), (), ())


class FactCatalog:
    """Catalog the behavioral facts of a domain's method bodies.

    One catalog per :class:`~protean.ir.builder.IRBuilder`, sharing that
    builder's provider, index, and resolver so a module a rule already read is
    not parsed again. Facts for a method are computed on first request and
    cached, so a build whose rules never ask pays nothing.
    """

    def __init__(
        self,
        domain: Domain,
        provider: SourceProvider | None = None,
        index: ElementIndex | None = None,
        resolver: SymbolResolver | None = None,
    ) -> None:
        self._domain = domain
        self._provider = provider if provider is not None else SourceProvider(domain)
        self._index = (
            index if index is not None else ElementIndex(domain, self._provider)
        )
        self._resolver = (
            resolver if resolver is not None else SymbolResolver(domain, self._provider)
        )
        # (module, id(node)) -> its facts. Node identity is stable: the trees
        # are the provider's, held for its lifetime and shared with every layer.
        self._cache: dict[tuple[str, int], MethodFacts] = {}

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def method_facts(self, module: str, method: FunctionNode) -> MethodFacts:
        """The facts of one method body, computed once and cached.

        ``module`` is the name the method's tree is cached under, used to
        resolve names and to locate the source file. A method whose module has
        no origin still yields facts; their locations simply carry no path.
        """
        key = (module, id(method))
        facts = self._cache.get(key)
        if facts is None:
            facts = self._collect(module, method)
            self._cache[key] = facts
        return facts

    def element_facts(self, cls: type) -> dict[str, MethodFacts]:
        """Every method of a registered element, name -> its facts.

        Resolves ``cls`` through the shared index, so an element whose source is
        unavailable or ambiguous yields an empty mapping (fail open). The
        methods are those written in the class body, in name order, matching the
        index; a nested class's methods are not among them.
        """
        entry = self._index.element_class_entry(cls)
        if entry is None:
            return {}
        return {
            method.name: self.method_facts(entry.module, method.node)
            for method in entry.methods
        }

    # ------------------------------------------------------------------
    # Collection
    # ------------------------------------------------------------------

    def _collect(self, module: str, method: FunctionNode) -> MethodFacts:
        """Walk a method body and gather its three fact kinds."""
        path = self._provider.origin(module)
        calls: list[CallFact] = []
        attributes: list[AttributeFact] = []
        constructions: list[ConstructionFact] = []

        def visit(node: ast.AST, is_callee: bool) -> None:
            if isinstance(node, _NESTED_SCOPES):
                # A fact inside a nested function/lambda/class belongs to it,
                # not to the method being cataloged.
                return
            if isinstance(node, ast.Call):
                self._record_call(module, path, node, calls, constructions)
                # The callee names the method, not a data access; its receiver
                # and the argument expressions still carry facts of their own.
                visit(node.func, True)
                for arg in node.args:
                    visit(arg, False)
                for keyword in node.keywords:
                    visit(keyword.value, False)
                return
            if isinstance(node, ast.Attribute):
                if not is_callee:
                    attributes.append(self._attribute_fact(path, node))
                visit(node.value, False)
                return
            for child in ast.iter_child_nodes(node):
                visit(child, False)

        try:
            for statement in method.body:
                visit(statement, False)
        except RecursionError:
            # A method that parses but nests expressions deeper than the
            # interpreter's stack (a pathological attribute or operator chain)
            # must not raise out of a fail-open catalog. Drop to no facts rather
            # than emit a partial, order-dependent set.
            return _NO_FACTS

        return MethodFacts(
            tuple(sorted(calls, key=_position)),
            tuple(sorted(attributes, key=_position)),
            tuple(sorted(constructions, key=_position)),
        )

    def _record_call(
        self,
        module: str,
        path: str | None,
        node: ast.Call,
        calls: list[CallFact],
        constructions: list[ConstructionFact],
    ) -> None:
        """Record a call as a construction or a call fact, never both."""
        location = _location(path, node)
        callee_fqn = self._resolver.resolve(module, node.func)
        method = _callee_name(node.func)

        if callee_fqn is not None and self._resolver.is_domain_element(callee_fqn):
            field_names, dynamic = _keyword_fields(node)
            constructions.append(
                ConstructionFact(callee_fqn, field_names, dynamic, location)
            )
            return

        role, receiver_fqn = self._receiver_role(module, node.func, method)
        # Field extraction follows the method-name surface, not the receiver
        # role: a query call names the same fields whether or not its receiver
        # could be tied to a repository, so a variable-held ``repo.find(Q(...))``
        # reports its fields as consistently as a recognized one does.
        field_names, dynamic = self._call_fields(module, node, method in _QUERY_METHODS)
        calls.append(
            CallFact(
                callee_fqn,
                method,
                receiver_fqn,
                role,
                field_names,
                dynamic,
                location,
            )
        )

    def _attribute_fact(self, path: str | None, node: ast.Attribute) -> AttributeFact:
        """Build an attribute read/write fact from an ``ast.Attribute`` node."""
        receiver = node.value.id if isinstance(node.value, ast.Name) else None
        is_write = isinstance(node.ctx, (ast.Store, ast.Del))
        return AttributeFact(node.attr, receiver, is_write, _location(path, node))

    # ------------------------------------------------------------------
    # Receiver role
    # ------------------------------------------------------------------

    def _receiver_role(
        self, module: str, func: ast.expr, method: str | None
    ) -> tuple[ReceiverRole, str | None]:
        """Classify the receiver of a call, and report the FQN it resolves to.

        A bare-name call (``Order(...)``, ``helper(...)``) has no receiver, so
        it is :attr:`ReceiverRole.UNKNOWN`. Otherwise the receiver is the object
        the method is called on; it is classified only when statically
        recognizable, and left unknown when it is a plain variable.
        """
        if not isinstance(func, ast.Attribute):
            return ReceiverRole.UNKNOWN, None

        receiver = func.value
        receiver_fqn = self._resolver.resolve(module, receiver)
        if not self._receiver_recognized(module, receiver, receiver_fqn):
            return ReceiverRole.UNKNOWN, receiver_fqn

        if self._is_unit_of_work(module, receiver, receiver_fqn):
            return ReceiverRole.UNIT_OF_WORK, receiver_fqn
        if method == _RAISE_METHOD:
            return ReceiverRole.RAISE_, receiver_fqn
        if method in _QUERY_METHODS:
            return ReceiverRole.REPOSITORY_QUERY, receiver_fqn
        return ReceiverRole.UNKNOWN, receiver_fqn

    def _receiver_recognized(
        self, module: str, receiver: ast.expr, receiver_fqn: str | None
    ) -> bool:
        """Whether a receiver is statically recognizable, not a plain variable.

        Recognizable: the whole chain resolves; or it is a name/attribute chain
        rooted at ``self`` or at a module-level name the resolver knows; or it is
        a construction of a domain element or the Unit of Work
        (``UnitOfWork().commit()``). A chain rooted at a local variable (``repo``,
        ``repo.query``) is not — that needs dataflow — and neither is an
        arbitrary call result (``get_repo().filter(...)``), which is less
        knowable than a variable, not more.
        """
        if receiver_fqn is not None:
            return True
        root = _root_name(receiver)
        if root is not None:
            return (
                root == "self" or self._resolver.symbols(module).get(root) is not None
            )
        # A construction receiver has no name root, but only a construction of a
        # domain element or the Unit of Work is recognizable — an arbitrary call
        # result (``get_repo().filter(...)``) is *less* knowable than a plain
        # variable, so it must stay unknown, not be waved through as a query.
        if isinstance(receiver, ast.Call):
            callee = self._resolver.resolve(module, receiver.func)
            return callee is not None and (
                callee == _UNIT_OF_WORK_FQN or self._resolver.is_domain_element(callee)
            )
        return False

    def _is_unit_of_work(
        self, module: str, receiver: ast.expr, receiver_fqn: str | None
    ) -> bool:
        """Whether a recognized receiver is the Unit of Work.

        Either it resolves to the Unit-of-Work FQN, or it is an inline
        ``UnitOfWork()`` construction. A ``uow`` bound to a local variable is not
        recognized here and never reaches this check.
        """
        if receiver_fqn == _UNIT_OF_WORK_FQN:
            return True
        if isinstance(receiver, ast.Call):
            return self._resolver.resolve(module, receiver.func) == _UNIT_OF_WORK_FQN
        return False

    # ------------------------------------------------------------------
    # Field names
    # ------------------------------------------------------------------

    def _call_fields(
        self, module: str, node: ast.Call, include_q: bool
    ) -> tuple[tuple[str, ...], bool]:
        """Field names a call passes: its keywords, plus inline ``Q`` fields.

        ``include_q`` is set for a query-surface call (``find``/``filter``/...),
        where a positional ``Q(field=...)`` names a query field. A ``Q`` held in
        a variable, or composed with ``&``/``|``, is not an ``ast.Call`` on
        ``Q`` and adds nothing.
        """
        names, dynamic = _keyword_fields(node)
        if not include_q:
            return names, dynamic
        collected = list(names)
        for arg in node.args:
            if not isinstance(arg, ast.Call):
                continue
            if self._resolver.resolve(module, arg.func) != _Q_FQN:
                continue
            q_names, q_dynamic = _keyword_fields(arg)
            dynamic = dynamic or q_dynamic
            for name in q_names:
                if name not in collected:
                    collected.append(name)
        return tuple(collected), dynamic


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _keyword_fields(node: ast.Call) -> tuple[tuple[str, ...], bool]:
    """The keyword field names of a call, and whether it has a ``**kwargs`` star.

    A keyword with a name (``status=...``) contributes that name; a double-star
    keyword (``**filters``) has no name and instead marks the call dynamic, so a
    field set is never fabricated for it.
    """
    names: list[str] = []
    dynamic = False
    for keyword in node.keywords:
        if keyword.arg is None:
            dynamic = True
        else:
            names.append(keyword.arg)
    return tuple(names), dynamic


def _callee_name(func: ast.expr) -> str | None:
    """The trailing name of a callee — its method or function name — or ``None``.

    ``x.method(...)`` gives ``method``, ``func(...)`` gives ``func``; a computed
    callee (a call result, a subscript) gives ``None``.
    """
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _root_name(node: ast.expr) -> str | None:
    """The base name of a name or attribute chain, or ``None``.

    ``self`` -> ``self``, ``self._dao`` -> ``self``, ``a.b.c`` -> ``a``.
    Anything whose base is not a plain name (a call result, a subscript) is
    ``None``.
    """
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _location(path: str | None, node: ast.AST) -> SourceLocation:
    """The source location of a node, path included."""
    return SourceLocation(
        path, getattr(node, "lineno", 0), getattr(node, "col_offset", 0)
    )


def _position(
    fact: CallFact | AttributeFact | ConstructionFact,
) -> tuple[int, int]:
    """The ``(line, col)`` sort key that orders facts deterministically."""
    return (fact.location.line, fact.location.col)
