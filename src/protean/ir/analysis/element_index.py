"""Class and method index over a domain's parsed sources.

:class:`ElementIndex` is the second layer of the ``protean check`` behavioral
substrate. :class:`~protean.ir.analysis.source_provider.SourceProvider` hands
out module trees; this turns those trees into a map a rule can query directly:

- every ``class`` in the domain's package, keyed by ``(module, qualname)``;
- every method of those classes, as its ``ast.FunctionDef`` or
  ``ast.AsyncFunctionDef`` node;
- a role tag per method, where the class is a registered domain element and the
  role follows from the element's type plus the method's decorators.

Internal API. Nothing here is re-exported from ``protean`` or ``protean.ir``.

Keys are ``__qualname__``-shaped
-------------------------------
A class is keyed by the dotted path Python itself would give it: enclosing
class names, and ``<locals>`` for a class defined inside a function
(``build_domain.<locals>.Wallet``). Building the key the way CPython builds
``__qualname__`` is what makes :meth:`ElementIndex.element_class_node` a dict
lookup rather than a name search, and it is what stops an element defined
inside a function from binding to an unrelated module-level class of the same
name. When a module defines the same qualname twice, the **first** definition
in source order is the one indexed, so the answer does not depend on walk
order.

Two doors, in a fixed order
---------------------------
The package walk runs first and indexes every module on disk under the domain's
root, including helper modules that register no element. Only then does a
lookup for a registered element whose ``__module__`` is outside that package
fall back to resolving the module by name. That order is deliberate: the
provider lets the on-disk walk override what name resolution cached, so
indexing the walk first means the index never holds a node from a file the
provider would later replace.

Contracts
---------
- **Fail open.** No lookup raises. A class with no source, no resolvable
  module, or a qualname that is not in the tree resolves to ``None``, and the
  rule that asked skips it.
- **Read-only nodes.** The nodes handed out belong to the provider's cached
  trees and are shared with every other caller. Mutating one corrupts every
  later rule's view of that module.
- **Deterministic order.** Every iteration surface returns a sorted tuple.

Decorator matching is deliberately shallow
------------------------------------------
A decorator is reduced to the **last dotted segment** of its expression, so
``@handle``, ``@mixins.handle`` and ``@handle(OrderPlaced)`` all read as
``handle``. Imports and aliases are not resolved, so a same-named decorator
from an unrelated library reads the same way. That is a knowingly conservative
placeholder for real name resolution, which is a later layer of this substrate;
it is acceptable here because no shipping rule consumes these tags yet, and it
must not be inherited as intent. A decorator that cannot be reduced to a plain
name (a subscript, a lambda call) is dropped rather than guessed.
"""

from __future__ import annotations

import ast
from enum import StrEnum
from typing import TYPE_CHECKING

from protean.ir.analysis.source_provider import SourceProvider
from protean.utils import DomainObjects

if TYPE_CHECKING:
    from protean.domain import Domain

#: A method body node, sync or async. Every check against one of these must
#: admit both: Protean handlers are commonly ``async def``, and matching only
#: ``ast.FunctionDef`` silently yields an empty method map for them.
FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


class MethodRole(StrEnum):
    """What a method *is*, where that follows from its element's type.

    A method carries at most one role, and only classes registered as domain
    elements carry roles at all. Everything else — a helper class, a private or
    dunder method, a method whose decorators say nothing — is untagged.
    """

    COMMAND_HANDLER_METHOD = "COMMAND_HANDLER_METHOD"
    EVENT_HANDLER_METHOD = "EVENT_HANDLER_METHOD"
    PROJECTOR_ON_EVENT = "PROJECTOR_ON_EVENT"
    EVENT_APPLY = "EVENT_APPLY"
    AGGREGATE_BEHAVIOR = "AGGREGATE_BEHAVIOR"
    REPOSITORY_METHOD = "REPOSITORY_METHOD"


class MethodEntry:
    """One method of an indexed class."""

    __slots__ = ("decorators", "name", "node")

    def __init__(self, name: str, node: FunctionNode, decorators: tuple[str, ...]):
        self.name = name
        self.node = node
        #: Trailing dotted segments of the method's decorators, in source
        #: order. Decorators that do not reduce to a plain name are absent.
        self.decorators = decorators

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MethodEntry {self.name} line {self.node.lineno}>"


class ClassEntry:
    """One indexed class, with its methods."""

    __slots__ = ("_methods", "module", "node", "qualname")

    def __init__(
        self,
        module: str,
        qualname: str,
        node: ast.ClassDef,
        methods: dict[str, MethodEntry],
    ):
        self.module = module
        self.qualname = qualname
        self.node = node
        self._methods = methods

    @property
    def methods(self) -> tuple[MethodEntry, ...]:
        """The class's own methods, sorted by name.

        Only direct children of the class body count: a function nested inside
        a method is not a method of the class.
        """
        return tuple(self._methods[name] for name in sorted(self._methods))

    def method(self, name: str) -> MethodEntry | None:
        """The method called ``name``, or ``None``."""
        return self._methods.get(name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ClassEntry {self.module}:{self.qualname}>"


class ElementIndex:
    """Map a domain's classes and methods to their source nodes.

    One index per :class:`~protean.ir.builder.IRBuilder`, sharing that builder's
    provider. The package walk is done once, on the first query, so a build
    whose rules never ask pays nothing.
    """

    def __init__(self, domain: Domain, provider: SourceProvider | None = None) -> None:
        self._domain = domain
        self._provider = provider if provider is not None else SourceProvider(domain)
        # Module name -> qualname -> entry. Holds both walked modules and
        # modules resolved on demand; an unparseable or unresolvable module is
        # recorded as an empty mapping so it is attempted exactly once.
        self._modules: dict[str, dict[str, ClassEntry]] = {}
        # Module names the package walk produced. ``classes()`` reports only
        # these, so its answer does not depend on which elements happened to be
        # resolved on demand first.
        self._package_modules: tuple[str, ...] = ()
        self._walked = False
        self._element_types: dict[tuple[str, str], str] | None = None

    # ------------------------------------------------------------------
    # Package-wide access
    # ------------------------------------------------------------------

    def classes(self) -> tuple[ClassEntry, ...]:
        """Every class in the domain's package, sorted by module then qualname.

        Whole-package scope: a class in a helper module that registers no
        element is indexed too. Classes resolved on demand for an element
        outside the package are *not* reported here, so this stays a function
        of the package alone.
        """
        self._walk_package()
        return tuple(
            self._modules[module][qualname]
            for module in self._package_modules
            for qualname in sorted(self._modules[module])
        )

    def class_node(self, module: str, qualname: str) -> ast.ClassDef | None:
        """The ``ast.ClassDef`` for ``qualname`` in ``module``, or ``None``."""
        entry = self.class_entry(module, qualname)
        return entry.node if entry is not None else None

    def class_entry(self, module: str, qualname: str) -> ClassEntry | None:
        """The indexed class, or ``None`` if the module or qualname is absent.

        ``qualname`` is matched in full, ``<locals>`` segments included, so a
        qualname whose defining function is not in the tree resolves to
        ``None`` rather than to a same-named class elsewhere in the module.
        """
        return self._module_index(module).get(qualname)

    def methods(self, module: str, qualname: str) -> tuple[MethodEntry, ...]:
        """The methods of ``qualname`` in ``module``, sorted by name."""
        entry = self.class_entry(module, qualname)
        return entry.methods if entry is not None else ()

    # ------------------------------------------------------------------
    # Element access
    # ------------------------------------------------------------------

    def element_class_entry(self, cls: type) -> ClassEntry | None:
        """The indexed class for a Python class object, or ``None``.

        Resolution is by ``(__module__, __qualname__)``. A class whose module
        has no source (built-in, dynamically created, not importable), or whose
        qualname is not in that module's tree, yields ``None``.
        """
        module = getattr(cls, "__module__", None)
        qualname = getattr(cls, "__qualname__", None)
        if not isinstance(module, str) or not isinstance(qualname, str):
            return None
        return self._module_index(module).get(qualname)

    def element_class_node(self, cls: type) -> ast.ClassDef | None:
        """The ``ast.ClassDef`` a class was defined by, or ``None``."""
        entry = self.element_class_entry(cls)
        return entry.node if entry is not None else None

    def element_methods(self, cls: type) -> tuple[MethodEntry, ...]:
        """The methods of a class as written, sorted by name."""
        entry = self.element_class_entry(cls)
        return entry.methods if entry is not None else ()

    def role_of(self, cls: type, method_name: str) -> MethodRole | None:
        """The role of ``cls.method_name``, or ``None`` if it has none.

        ``None`` covers every reason a role is not derivable: the class is not
        a registered element, it is registered but framework-internal, its
        source is unavailable, the method is not in the class body, or nothing
        about the element's type and the method's decorators names a role.
        """
        element_type = self._element_type(cls)
        if element_type is None:
            return None
        entry = self.element_class_entry(cls)
        if entry is None:
            return None
        method = entry.method(method_name)
        if method is None:
            return None
        return _role(element_type, method)

    def roles(self, cls: type) -> dict[str, MethodRole]:
        """Every method of ``cls`` that carries a role, name -> role."""
        element_type = self._element_type(cls)
        if element_type is None:
            return {}
        entry = self.element_class_entry(cls)
        if entry is None:
            return {}
        roles = {}
        for method in entry.methods:
            role = _role(element_type, method)
            if role is not None:
                roles[method.name] = role
        return roles

    # ------------------------------------------------------------------
    # Index construction
    # ------------------------------------------------------------------

    def _module_index(self, module: str) -> dict[str, ClassEntry]:
        """The index for one module, walking the package first if needed.

        The package walk always runs before a module is resolved by name, so
        the index never caches a tree the provider's walk would later override.
        """
        self._walk_package()
        if module in self._modules:
            return self._modules[module]

        tree = self._provider.tree(module)
        entries = _index_tree(module, tree) if tree is not None else {}
        self._modules[module] = entries
        return entries

    def _walk_package(self) -> None:
        """Index every module the provider finds on disk. Runs once."""
        if self._walked:
            return
        # Set before iterating: ``_index_tree`` cannot re-enter, but marking
        # first keeps a single walk even if a future caller does.
        self._walked = True
        names = []
        for module, tree in self._provider.iter_trees():
            self._modules[module] = _index_tree(module, tree)
            names.append(module)
        self._package_modules = tuple(names)

    def _element_type(self, cls: type) -> str | None:
        """The registered ``DomainObjects`` value for a class, or ``None``.

        Framework-internal elements are excluded: they are Protean's own
        machinery, not the user's domain, and tagging their methods as domain
        roles would put framework code in a rule's findings.
        """
        if self._element_types is None:
            self._element_types = _registered_element_types(self._domain)
        module = getattr(cls, "__module__", None)
        qualname = getattr(cls, "__qualname__", None)
        if not isinstance(module, str) or not isinstance(qualname, str):
            return None
        return self._element_types.get((module, qualname))


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _registered_element_types(domain: Domain) -> dict[tuple[str, str], str]:
    """Map ``(module, qualname)`` to element type for a domain's elements.

    Keyed by module and qualname rather than by the class object because
    Protean recreates element classes via ``type()`` in places; the identity
    that survives that is the name pair, which is also what the index is keyed
    by.
    """
    types: dict[tuple[str, str], str] = {}
    for element_type, records in domain._domain_registry._elements.items():
        for record in records.values():
            if record.internal:
                continue
            module = getattr(record.cls, "__module__", None)
            qualname = getattr(record.cls, "__qualname__", None)
            if isinstance(module, str) and isinstance(qualname, str):
                types.setdefault((module, qualname), element_type)
    return types


def _index_tree(module: str, tree: ast.Module) -> dict[str, ClassEntry]:
    """Index every class in one module tree, keyed by qualname."""
    entries: dict[str, ClassEntry] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                qualname = f"{prefix}{child.name}"
                # First definition wins, so a name defined twice in one module
                # resolves the same way regardless of how the tree is walked.
                if qualname not in entries:
                    entries[qualname] = ClassEntry(
                        module, qualname, child, _class_methods(child)
                    )
                walk(child, f"{qualname}.")
            elif isinstance(child, FunctionNode):
                # A class defined inside a function gets the ``<locals>``
                # segment CPython puts in ``__qualname__``.
                walk(child, f"{prefix}{child.name}.<locals>.")
            else:
                # Classes hide inside ``if``/``try``/``with`` bodies too.
                walk(child, prefix)

    walk(tree, "")
    return entries


def _class_methods(node: ast.ClassDef) -> dict[str, MethodEntry]:
    """The direct method children of a class body, first definition winning."""
    methods: dict[str, MethodEntry] = {}
    for child in node.body:
        if isinstance(child, FunctionNode) and child.name not in methods:
            methods[child.name] = MethodEntry(
                child.name, child, _decorator_names(child)
            )
    return methods


def _decorator_names(node: FunctionNode) -> tuple[str, ...]:
    """Trailing dotted segments of a function's decorators, in source order.

    A decorator that does not reduce to a plain name is omitted rather than
    represented by a guess.
    """
    names = []
    for decorator in node.decorator_list:
        name = _decorator_name(decorator)
        if name is not None:
            names.append(name)
    return tuple(names)


def _decorator_name(node: ast.expr) -> str | None:
    """The last dotted segment of a decorator expression, or ``None``."""
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


#: Decorator names that mark a handler method. ``on`` is the projector-facing
#: alias of ``handle``, so both read the same way on a projector.
_HANDLE = "handle"
_ON = "on"
_APPLY = "apply"


def _role(element_type: str, method: MethodEntry) -> MethodRole | None:
    """Derive a method's role from its element type and its decorators."""
    decorators = method.decorators
    public = not method.name.startswith("_")

    if element_type == DomainObjects.COMMAND_HANDLER.value:
        if _HANDLE in decorators:
            return MethodRole.COMMAND_HANDLER_METHOD
        return None

    if element_type in (
        DomainObjects.EVENT_HANDLER.value,
        DomainObjects.PROCESS_MANAGER.value,
    ):
        if _HANDLE in decorators:
            return MethodRole.EVENT_HANDLER_METHOD
        return None

    if element_type == DomainObjects.PROJECTOR.value:
        if _HANDLE in decorators or _ON in decorators:
            return MethodRole.PROJECTOR_ON_EVENT
        return None

    if element_type == DomainObjects.AGGREGATE.value:
        # ``@apply`` first: an apply method is an event application, not a
        # behavior, even though it is public and undecorated-looking otherwise.
        if _APPLY in decorators:
            return MethodRole.EVENT_APPLY
        if public:
            return MethodRole.AGGREGATE_BEHAVIOR
        return None

    if element_type in (
        DomainObjects.REPOSITORY.value,
        DomainObjects.EVENT_SOURCED_REPOSITORY.value,
    ):
        if public:
            return MethodRole.REPOSITORY_METHOD
        return None

    return None
