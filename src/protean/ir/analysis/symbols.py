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
relative import that escapes binds none.

Shadowing: local definitions win over imports
---------------------------------------------
Imports are recorded first, then local ``class``/``def`` bindings overwrite
them, so a module-level class that shadows a same-named import resolves to the
local definition's FQN. That matches Python's last-binding-wins semantics for
that shape, and it is deterministic: build order, not tree-walk order, decides.

Use-site resolution
-------------------
:meth:`resolve` takes a module name and an expression node:

- an ``ast.Name`` is looked up in the table;
- an ``ast.Attribute`` chain (``mixins.handle``, ``pkg.Thing``) is resolved
  through its root ``ast.Name`` and the trailing segments appended to the root's
  FQN;
- anything else — a call result, a subscript, ``self.x`` (its root ``self`` is
  never in the table) — is ``None``.

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
from typing import TYPE_CHECKING

from protean.ir.analysis.source_provider import SourceProvider

if TYPE_CHECKING:
    from protean.domain import Domain

#: Module-level statements that bind a name to a definition in this module.
#: A class, a function, or an ``async def`` at module scope binds its own name
#: to ``<module>.<name>``, and does so *after* imports so a local definition
#: shadows a same-named import.
_DEF_NODES = (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


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
        # Imports first: a local definition below binds the same name last, and
        # Python's last-binding-wins means the local definition should stand.
        for statement in tree.body:
            if isinstance(statement, ast.Import):
                self._bind_import(table, statement)
            elif isinstance(statement, ast.ImportFrom):
                self._bind_import_from(table, module, statement)
        for statement in tree.body:
            if isinstance(statement, _DEF_NODES):
                table[statement.name] = f"{module}.{statement.name}"
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
