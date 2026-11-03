"""Name and symbol resolution over a domain's parsed sources.

:class:`SymbolResolver` is the third layer of the ``protean check`` behavioral
substrate. :class:`~protean.ir.analysis.source_provider.SourceProvider` hands
out module trees; this turns a *use-site name* in one of those trees into the
fully-qualified name (FQN) it refers to, where that is statically determinable,
and returns ``None`` everywhere it is not.

Internal API. Nothing here is re-exported from ``protean`` or ``protean.ir``.

The one rule: never guess
-------------------------
Every method has a single "I don't know" answer — ``None`` from
:meth:`resolve`, an absent key in a symbol table, ``False`` from a predicate
handed an FQN that resolves to nothing. A use site that cannot be resolved to
exactly one FQN is left unresolved rather than bound to a plausible-but-wrong
one, because a wrong FQN feeds a downstream false positive and a miss does not.

Per-module symbol table
-----------------------
:meth:`resolve` works off a ``name -> FQN`` table built once per module from its
**module-level** bindings, alias-aware:

- ``import a.b.c`` binds ``a`` to ``a`` — Python binds the top name, and an
  attribute walk off it (``a.b.c.Thing``) reconstructs the rest.
- ``import a.b.c as w`` binds ``w`` to ``a.b.c``.
- ``from a.b import c`` binds ``c`` to ``a.b.c``; ``... as d`` binds ``d``.
- A relative import (``from . import x``, ``from ..p import y``) is anchored on
  the module's package, computed from its origin: an ``__init__`` file means the
  module name *is* the package, otherwise the package is the module name minus
  its last segment. The import is then resolved with Python's own rule (go up
  ``level - 1`` packages). One that walks past the top-level package, or whose
  package cannot be determined, leaves its names **unresolved** rather than
  fabricating an FQN.
- A module-level ``class`` / ``def`` / ``async def`` binds its name to
  ``<module>.<name>``.

Only the module's top-level statements are read, so a name bound solely inside a
conditional or a function body is conservatively absent from the table (it
resolves to ``None``, never to a wrong FQN). A ``*`` import binds no name and a
relative import that escapes binds none. :meth:`resolve` and :meth:`symbols`
keep this module-only meaning; method-local imports are read only through a
:class:`MethodScope`.

Shadowing: the last binding in source order wins
------------------------------------------------
The table is built in a single top-level pass, so a name bound more than once
takes its **last** binding — exactly as Python binds a module-level name at
runtime. A ``class``/``def`` after a same-named import shadows the import; an
import after a same-named definition shadows the definition. A module-level
assignment (``x = ...``, ``x: T = ...``, ``x += ...``) rebinds its target to a
value this static table cannot follow, so it *removes* that name rather than
keep a now-stale FQN — the name resolves to ``None`` (a miss, never a wrong
FQN). Attribute and subscript targets (``a.b = ...``) rebind no module name.

Use-site resolution
-------------------
:meth:`resolve` takes a module name and an expression node:

- an ``ast.Name`` is looked up in the table;
- an ``ast.Attribute`` chain (``mixins.handle``, ``pkg.Thing``) is resolved
  through its root ``ast.Name`` and the trailing segments appended to the root's
  FQN;
- anything else — a call result, a subscript, ``self.x`` (its root ``self`` is
  never in the table) — is ``None``.

Method-local imports
--------------------
:meth:`SymbolResolver.method_scope` reads the ``import`` and ``from ... import``
statements written inside one method body, and the returned
:class:`MethodScope` resolves use sites in that body:

- An import anywhere in the body counts, including inside ``if``, ``try``,
  ``with``, ``for`` and ``while``. One inside a nested ``def``, ``async def``,
  ``lambda`` or ``class`` binds nothing for the method.
- A name a method-local import binds resolves to that import's FQN for a use
  after the first such import, by ``(line, col)``. A use at or before it
  resolves to ``None``: unless the method declares it ``global``, Python treats
  the name as local for the whole function, so the module binding would be
  wrong there.
- A method-local binding shadows a module-level binding of the same name.
- Two method-local imports that give a name different FQNs leave it ``None``.
  So does a relative import that escapes the top-level package, a ``global`` or
  ``nonlocal`` declaration of the name, and any other binding of the name in the
  body (an assignment, a ``for``/``with``/``except`` target, a walrus, a ``del``,
  a nested ``def`` or ``class``, a ``nonlocal`` rebinding from a nested ``def``,
  a walrus in a nested scope's decorators, defaults or bases). Two imports with
  the same FQN still bind it.
- A parameter of the same name leaves it ``None`` too, unless the first import
  of the name is a statement of the body itself, outside any ``if``, ``try``,
  loop or ``with``. That import always runs, so it replaces the argument for
  every later use.
- A name no method-local import binds resolves through the module table.

Classification predicates
-------------------------
Given a resolved FQN, :meth:`is_framework_symbol` says whether it names Protean
itself, and :meth:`is_domain_element` whether it names a registered element. The
element set is snapshotted on first use from the domain registry, matching the
one-resolver-per-build lifetime the other layers keep: an element registered
after that first query is invisible to it.

Contracts
---------
- **Fail open.** A module with no source, or one that does not parse, yields an
  empty table, and :meth:`resolve` over it returns ``None``. No lookup raises for
  a missing or unparseable module.
- **Analysis is of source as written.** The table is built from the AST, not
  from what the import system would load at runtime, which is what makes it
  reproducible. It does not import anything.
- **Deterministic.** Two resolvers over the same source produce the same table
  and the same answers.
- **Single-threaded.** One resolver per build, sharing that build's provider;
  give each thread its own, as with the other layers.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from protean.ir.analysis.source_provider import SourceProvider

if TYPE_CHECKING:
    from protean.domain import Domain
    from protean.ir.analysis.element_index import FunctionNode

#: Module-level statements that bind a name to a definition in this module.
#: A class, a function, or an ``async def`` at module scope binds its own name
#: to ``<module>.<name>``. Bindings are applied in source order, so whichever of
#: a definition and a same-named import comes last is the one that stands.
_DEF_NODES = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

#: Scopes a walk of one method body does not descend into: a name bound or a
#: call made inside one of these belongs to that nested callable, not to the
#: method enclosing it.
NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

#: A ``(line, col)`` source position, as the AST records it on a node.
_Position = tuple[int, int]


@dataclass(frozen=True, slots=True)
class _LocalBinding:
    """A name bound by a method-local import.

    ``position`` is that of the first import that binds it. ``fqn`` is ``None``
    when the method's bindings of the name disagree or cannot be resolved.
    """

    position: _Position
    fqn: str | None


class MethodScope:
    """Resolve use sites in one method body, method-local imports included.

    Built by :meth:`SymbolResolver.method_scope`. A name with no method-local
    import resolves exactly as :meth:`SymbolResolver.resolve` resolves it.
    """

    def __init__(
        self,
        resolver: SymbolResolver,
        module: str,
        bindings: dict[str, _LocalBinding],
    ) -> None:
        self._resolver = resolver
        self._module = module
        self._bindings = bindings

    def resolve(self, node: ast.expr) -> str | None:
        """The FQN a use-site expression in this method names, or ``None``.

        Accepts the same shapes as :meth:`SymbolResolver.resolve`.
        """
        parts = _dotted_parts(node)
        if parts is None:
            return None
        binding = self._bindings.get(parts[0])
        if binding is None:
            return self._resolver.resolve(self._module, node)
        if binding.fqn is None or _position_of(node) <= binding.position:
            return None
        return ".".join([binding.fqn, *parts[1:]])


class SymbolResolver:
    """Resolve a use-site name to its fully-qualified name over parsed sources.

    One resolver per :class:`~protean.ir.builder.IRBuilder`, sharing that
    builder's provider, so a module a rule already read is not parsed again.
    Each module's symbol table is built once, on the first :meth:`resolve` for
    that module, so a build whose rules never ask pays nothing.
    """

    def __init__(self, domain: Domain, provider: SourceProvider | None = None) -> None:
        self._domain = domain
        self._provider = provider if provider is not None else SourceProvider(domain)
        # Module name -> its ``name -> FQN`` table. An unresolvable or
        # unparseable module is recorded as an empty table so it is attempted
        # exactly once.
        self._tables: dict[str, dict[str, str]] = {}
        # The registered-element FQN set, snapshotted on first use.
        self._element_fqns: frozenset[str] | None = None

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, module: str, node: ast.expr) -> str | None:
        """The FQN a use-site expression names in ``module``, or ``None``.

        ``node`` is a use site: an ``ast.Name`` or an ``ast.Attribute`` chain
        rooted at a name. A name is looked up in the module's symbol table; an
        attribute chain resolves its root name and appends the trailing dotted
        segments. Every other shape — and any root that is not in the table —
        is ``None``, the single "unresolved" answer.
        """
        parts = _dotted_parts(node)
        if parts is None:
            return None
        root = self.symbols(module).get(parts[0])
        if root is None:
            return None
        return ".".join([root, *parts[1:]])

    def symbols(self, module: str) -> dict[str, str]:
        """The ``name -> FQN`` table for ``module``, built once and cached.

        Empty when the module has no source or does not parse. The returned
        mapping is the resolver's own cache; callers must not mutate it.
        """
        table = self._tables.get(module)
        if table is None:
            table = self._build_table(module)
            self._tables[module] = table
        return table

    def method_scope(self, module: str, method: FunctionNode) -> MethodScope:
        """The scope that resolves use sites in ``method``, a body in ``module``.

        Reads the imports written in the method body, outside any nested scope.
        The module's own table is not changed: :meth:`resolve` and
        :meth:`symbols` still answer from module-level bindings only.
        """
        bindings: dict[str, _LocalBinding] = {}
        rebound: set[str] = set()
        # Names whose first import is a statement of the body itself: it always
        # runs before any later use, so it replaces a parameter of that name.
        always_run: dict[str, _Position] = {}
        top_level = {id(statement) for statement in method.body}
        stack: list[ast.AST] = list(reversed(method.body))
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                self._bind_local_import(bindings, module, node)
                if id(node) in top_level:
                    for name in _imported_names(node):
                        always_run.setdefault(name, _position_of(node))
                continue
            rebound.update(_rebinding_names(node))
            stack.extend(_parts_in_method_scope(node))
        for name in _parameter_names(method) & bindings.keys():
            if always_run.get(name) != bindings[name].position:
                # The first import may not run, so a use after it can still see
                # the argument the caller passed.
                rebound.add(name)
        for name in rebound & bindings.keys():
            # The name is also bound to a value this static scope cannot follow,
            # so no single FQN is right for every use after the import.
            bindings[name] = _LocalBinding(bindings[name].position, None)
        return MethodScope(self, module, bindings)

    def _bind_local_import(
        self,
        bindings: dict[str, _LocalBinding],
        module: str,
        node: ast.Import | ast.ImportFrom,
    ) -> None:
        """Merge one method-local import statement into ``bindings``."""
        table: dict[str, str] = {}
        if isinstance(node, ast.Import):
            self._bind_import(table, node)
        else:
            self._bind_import_from(table, module, node)
        here = _position_of(node)
        for name in _imported_names(node):
            # A name the import binds but the table lacks came from a relative
            # import that escaped: it is still local, with no FQN.
            fqn = table.get(name)
            position = here
            existing = bindings.get(name)
            if existing is not None:
                position = min(here, existing.position)
                if existing.fqn != fqn:
                    fqn = None
            bindings[name] = _LocalBinding(position, fqn)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def is_framework_symbol(fqn: str) -> bool:
        """Whether ``fqn`` names Protean itself.

        ``protean`` and anything under it (``protean.core.aggregate.Aggregate``,
        ``protean.adapters...``). A name that resolved to ``None`` is not an FQN
        and is neither a framework symbol nor a domain element.
        """
        return fqn == "protean" or fqn.startswith("protean.")

    def is_domain_element(self, fqn: str) -> bool:
        """Whether ``fqn`` names a class registered as a domain element.

        Matched against the FQNs the registry recorded for non-internal
        elements (``module.__qualname__`` at registration time). Framework
        internals are excluded, for the same reason the element index leaves
        them untagged: they are Protean's machinery, not the user's domain.
        """
        if self._element_fqns is None:
            self._element_fqns = _registered_element_fqns(self._domain)
        return fqn in self._element_fqns

    # ------------------------------------------------------------------
    # Table construction
    # ------------------------------------------------------------------

    def _build_table(self, module: str) -> dict[str, str]:
        """Build ``module``'s symbol table from its top-level statements."""
        tree = self._provider.tree(module)
        if tree is None:
            return {}

        table: dict[str, str] = {}
        # One pass in source order: the last statement to bind a name wins,
        # matching how Python binds a module-level name at runtime. So a
        # definition after a same-named import shadows it, an import after a
        # same-named definition shadows that, and an assignment removes the name
        # (its new value is not statically followable) rather than leave a stale
        # FQN that would be a wrong answer.
        for statement in tree.body:
            if isinstance(statement, ast.Import):
                self._bind_import(table, statement)
            elif isinstance(statement, ast.ImportFrom):
                self._bind_import_from(table, module, statement)
            elif isinstance(statement, _DEF_NODES):
                table[statement.name] = f"{module}.{statement.name}"
            else:
                _unbind_assignments(table, statement)
        return table

    @staticmethod
    def _bind_import(table: dict[str, str], node: ast.Import) -> None:
        """Bind an ``import a.b.c`` / ``import a.b.c as w`` statement."""
        for alias in node.names:
            if alias.asname:
                # ``import a.b.c as w`` binds ``w`` to the imported module.
                table[alias.asname] = alias.name
            else:
                # ``import a.b.c`` binds the *top* name ``a``; the rest is
                # reached by walking attributes off it at the use site.
                top = alias.name.split(".", 1)[0]
                table[top] = top

    def _bind_import_from(
        self, table: dict[str, str], module: str, node: ast.ImportFrom
    ) -> None:
        """Bind a ``from ... import ...`` statement, relative or absolute."""
        if node.level:
            base = self._resolve_relative(module, node)
            if base is None:
                # Escaped the top-level package, or the package is unknown:
                # leave every name it would bind unresolved.
                return
        else:
            base = node.module
            if base is None:  # pragma: no cover - level 0 always carries a module
                return
        for alias in node.names:
            if alias.name == "*":
                # A star import binds no single name to resolve.
                continue
            bound = alias.asname or alias.name
            table[bound] = f"{base}.{alias.name}"

    def _resolve_relative(self, module: str, node: ast.ImportFrom) -> str | None:
        """The absolute module a relative ``from`` import reads from, or ``None``.

        Applies Python's own rule: anchor on the module's package, then go up
        ``level - 1`` further packages. Returns ``None`` when the import walks
        past the top-level package or the anchoring package cannot be formed.
        """
        package = self._package_of(module)
        # ``package.rsplit('.', level - 1)`` is exactly how CPython resolves a
        # relative name; too few parts means the import escaped the top level.
        bits = package.rsplit(".", node.level - 1)
        if len(bits) < node.level or not bits[0]:
            return None
        base = bits[0]
        return f"{base}.{node.module}" if node.module else base

    def _package_of(self, module: str) -> str:
        """The package a module belongs to, for anchoring relative imports.

        A module whose source is an ``__init__`` file *is* its package;
        otherwise the package is the module name minus its last segment (``""``
        for a top-level module, which cannot anchor a relative import).
        """
        origin = self._provider.origin(module)
        if origin is not None and _is_package_init(origin):
            return module
        return module.rpartition(".")[0]


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _dotted_parts(node: ast.expr) -> list[str] | None:
    """The dotted segments of a name or attribute chain, root first.

    ``Order`` -> ``["Order"]``, ``pkg.a.Thing`` -> ``["pkg", "a", "Thing"]``.
    Anything whose root is not a plain ``ast.Name`` — a call, a subscript, a
    literal — is ``None``, so it never reaches the table.
    """
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    parts.reverse()
    return parts


def _unbind_assignments(table: dict[str, str], statement: ast.stmt) -> None:
    """Drop any table name a module-level assignment rebinds.

    ``x = ...``, ``x: T = ...``, ``x += ...`` and unpacking assignments rebind
    ``x`` to a value this static table cannot follow. Rather than keep the FQN a
    prior import or definition left for ``x``, the name is removed so it
    resolves to ``None`` — a miss, never a wrong FQN. Attribute and subscript
    targets (``a.b = ...``) rebind no module name, and a bare annotation
    (``x: int`` with no value) binds nothing, so both are left untouched.
    """
    if isinstance(statement, ast.Assign):
        targets: list[ast.expr] = statement.targets
    elif isinstance(statement, ast.AugAssign) or (
        isinstance(statement, ast.AnnAssign) and statement.value is not None
    ):
        targets = [statement.target]
    else:
        return
    for target in targets:
        for name in _assigned_names(target):
            table.pop(name, None)


def _assigned_names(target: ast.expr) -> list[str]:
    """The plain names an assignment target binds, recursing into unpacking.

    ``x`` -> ``["x"]``, ``a, *b`` -> ``["a", "b"]``. Attribute and subscript
    targets bind no module name and yield nothing.
    """
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Starred):
        return _assigned_names(target.value)
    if isinstance(target, (ast.Tuple, ast.List)):
        names: list[str] = []
        for element in target.elts:
            names.extend(_assigned_names(element))
        return names
    return []


def _imported_names(node: ast.Import | ast.ImportFrom) -> list[str]:
    """The names an import statement binds in the scope it runs in.

    The compiler rejects a ``*`` import inside a function, but ``ast.parse``
    accepts one. It yields the name ``*``, which never matches a use-site root.
    """
    names: list[str] = []
    for alias in node.names:
        if alias.asname:
            names.append(alias.asname)
        elif isinstance(node, ast.Import):
            names.append(alias.name.split(".", 1)[0])
        else:
            names.append(alias.name)
    return names


def _bound_names(node: ast.AST) -> list[str]:
    """The plain names one node binds other than by an import.

    Covers every ``Store`` or ``Del`` name (assignment, augmented and annotated
    assignment, ``for``/``with`` targets, a walrus, ``del``), an ``except ... as``
    name, a ``match`` capture, and the name of a nested ``def``, ``async def`` or
    ``class``. A comprehension target binds only inside the comprehension, but it
    is counted too: the result is a miss, never a wrong FQN.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Name):
        return [node.id] if isinstance(node.ctx, (ast.Store, ast.Del)) else []
    if isinstance(node, ast.ExceptHandler):
        return [node.name] if node.name else []
    if isinstance(node, (ast.MatchAs, ast.MatchStar)):
        return [node.name] if node.name else []
    if isinstance(node, ast.MatchMapping):
        return [node.rest] if node.rest else []
    return []


def _rebinding_names(node: ast.AST) -> list[str]:
    """The names one non-import node in a method body binds for the method.

    Adds to :func:`_bound_names` a ``global`` or ``nonlocal`` declaration, after
    which the import binds an outer name that a use on a path skipping the
    import still sees, and a ``nonlocal`` declaration inside a nested scope.
    """
    names = _bound_names(node)
    if isinstance(node, (ast.Global, ast.Nonlocal)):
        names.extend(node.names)
    if isinstance(node, NESTED_SCOPES):
        names.extend(_nonlocal_names(node))
    return names


def _parts_in_method_scope(node: ast.AST) -> list[ast.AST]:
    """The child nodes of ``node`` that run in the method's own scope.

    All children of an ordinary node. Of a nested scope node, only the parts
    evaluated where it is defined, so a walrus in one binds the method's name.
    Of a bare annotation of a plain name (``x: int`` with no value), only the
    annotation: its target is a ``Store`` name, but nothing is bound to it at
    runtime. An attribute or subscript target is still evaluated, so a walrus
    inside it binds the method's name.
    """
    if isinstance(node, NESTED_SCOPES):
        return list(_enclosing_scope_parts(node))
    if (
        isinstance(node, ast.AnnAssign)
        and node.value is None
        and isinstance(node.target, ast.Name)
    ):
        return [node.annotation]
    return list(ast.iter_child_nodes(node))


def _parameter_names(method: FunctionNode) -> set[str]:
    """Every name ``method`` binds as a parameter, ``*args`` and ``**kwargs`` too."""
    args = method.args
    params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    params.extend(arg for arg in (args.vararg, args.kwarg) if arg is not None)
    return {param.arg for param in params}


def _enclosing_scope_parts(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef,
) -> list[ast.expr]:
    """The parts of a nested scope node that run in the scope enclosing it.

    Decorators, argument defaults and annotations, a return annotation, and a
    class's bases and keywords.
    """
    parts: list[ast.expr] = []
    if isinstance(node, ast.ClassDef):
        parts.extend(node.decorator_list)
        parts.extend(node.bases)
        parts.extend(keyword.value for keyword in node.keywords)
        return parts
    args = node.args
    parts.extend(args.defaults)
    parts.extend(default for default in args.kw_defaults if default is not None)
    if isinstance(node, ast.Lambda):
        return parts
    parts.extend(node.decorator_list)
    every_arg = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    every_arg.extend(arg for arg in (args.vararg, args.kwarg) if arg is not None)
    parts.extend(arg.annotation for arg in every_arg if arg.annotation is not None)
    if node.returns is not None:
        parts.append(node.returns)
    return parts


def _nonlocal_names(node: ast.AST) -> list[str]:
    """The names a ``nonlocal`` statement anywhere inside ``node`` declares.

    Such a name may be the method's own, rebound from the nested scope. One
    that names a scope in between is counted too, which costs a miss only.
    """
    names: list[str] = []
    for inner in ast.walk(node):
        if isinstance(inner, ast.Nonlocal):
            names.extend(inner.names)
    return names


def _position_of(node: ast.AST) -> _Position:
    """A node's ``(line, col)`` source position."""
    return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))


def _is_package_init(origin: str) -> bool:
    """Whether a source path is a package's ``__init__`` file."""
    return os.path.splitext(os.path.basename(origin))[0] == "__init__"


def _registered_element_fqns(domain: Domain) -> frozenset[str]:
    """The FQNs of every non-internal registered element.

    Read off ``record.qualname``, which registration set to the element's
    ``module.__qualname__``. Internal elements — Protean's own machinery — are
    excluded, so classifying a use site never marks framework code as domain.
    """
    fqns: set[str] = set()
    for records in domain._domain_registry._elements.values():
        for record in records.values():
            if record.internal:
                continue
            fqns.add(record.qualname)
    return frozenset(fqns)
