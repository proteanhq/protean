"""Class and method index over a domain's parsed sources.

:class:`ElementIndex` is the second layer of the ``protean check`` behavioral
substrate. :class:`~protean.ir.analysis.source_provider.SourceProvider` hands
out module trees; this turns those trees into a map a rule can query directly:

- every ``class`` in the modules the provider's package walk reaches, keyed by
  ``(module, qualname)``;
- every method of those classes, as its ``ast.FunctionDef`` or
  ``ast.AsyncFunctionDef`` node;
- a role tag per method, where the class is a registered domain element and the
  role follows from the element's type plus the method's decorators.

Internal API. Nothing here is re-exported from ``protean`` or ``protean.ir``.

Keys are ``__qualname__``-shaped
-------------------------------
A class is keyed by the dotted path Python itself would give it: enclosing
class names, and ``<locals>`` for a class defined inside a function
(``build_domain.<locals>.Wallet``). When a module defines the same qualname
twice, the **first** definition in source order is indexed, so the answer does
not depend on walk order. First rather than last is a coin toss between two
deterministic options — for an unconditional redefinition Python binds the
last, but for the realistic shape (``try: class X(CImpl) / except ImportError:
class X(PyImpl)``) neither branch is "the" answer, so the index takes the one
that is stable and says so rather than pretending to know.

Registered elements do not always keep their qualname
-----------------------------------------------------
``derive_element_class`` rebuilds an element that does not already subclass its
base via ``type(name, (base,), dict)``, and that resets ``__qualname__`` to the
bare class name. So a registered element written inside a function or inside
another class arrives here claiming to be module-level, and a module-level
class of the same name would answer for it. Element lookup handles this: a bare
qualname is matched against every class in the module whose final name segment
is that name, and when more than one is, the element is pinned by its own
functions — a rebuilt class keeps the function objects from the class body, and
each of those carries ``co_qualname``, the path the compiler recorded. If that
cannot single one out (an element with no methods of its own, say), the lookup
returns ``None`` rather than binding to a class it cannot prove is the right
one. A *dotted* qualname is still matched in full, ``<locals>`` segments
included.

Two doors, in a fixed order
---------------------------
The package walk runs first and indexes the modules the provider's walk yields.
Only then does a lookup for a registered element whose ``__module__`` is outside
that package fall back to resolving the module by name. That order is
deliberate: the provider lets the on-disk walk override what name resolution
cached, so indexing the walk first means the index never holds a node from a
file the provider would later replace.

The two doors name modules differently — the walk names them off the path
relative to the domain root's parent, name resolution off ``sys.path`` — so one
file can be indexed twice under two names. The nodes are then equal in position
but *not identical objects*, and a rule that joins the two surfaces must join on
``(module, qualname, lineno)``, not on node identity.

Contracts
---------
- **Fail open.** A class with no source, no resolvable module, or a qualname
  that cannot be pinned to one node resolves to ``None``, and the rule that
  asked skips it. Lookups do not raise for any of those reasons; they can still
  raise for a genuine interpreter limit (a module nested far past the recursion
  limit), which is not something to swallow.
- **Read-only nodes.** The nodes handed out belong to the provider's cached
  trees and are shared with every other caller under the same module name.
  Mutating one corrupts every later rule's view of that module. The entries
  wrapping them are frozen; the nodes themselves cannot be.
- **Deterministic order.** ``classes()`` and ``methods`` are sorted tuples;
  ``roles()`` is a dict in method-name order. ``MethodEntry.decorators`` is the
  exception: it is source order, because that is what it reports.
- **Single-threaded.** One index per build, queried from the thread that built
  it. The package walk is not guarded against concurrent entry, the same way
  :class:`SourceProvider` is not.
- **Registry snapshot.** The registered-element map is read once, on the first
  role query, and elements registered after that are invisible to it. That
  matches the one-index-per-build lifetime.

Decorator matching is deliberately shallow
------------------------------------------
A decorator is reduced to the **last dotted segment** of its expression, so
``@handle``, ``@mixins.handle`` and ``@handle(OrderPlaced)`` all read as
``handle``. (``@on`` is the one alias that is honoured, because it *is*
``handle`` — the same function under another name.) Imports and aliases beyond
that are not resolved, so a same-named decorator from an unrelated library
reads the same way, and ``@invariant.post`` reads as ``post``. That is a
knowingly conservative placeholder for real name
resolution, which is a later layer of this substrate; it is acceptable here
because no shipping rule consumes these tags yet, and it must not be inherited
as intent. A decorator that cannot be reduced to a plain name (a subscript, a
lambda call) is dropped rather than guessed.

Because the reduction is shallow, the two roles that would otherwise be derived
from "public method, nothing said otherwise" — aggregate behavior and
repository method — refuse to tag a method carrying any decorator known to mean
something else (``@property``, ``@classmethod``, ``@invariant.pre/post``, ...).
Leaving such a method untagged is a miss; tagging an invariant as behavior is a
wrong answer, and a wrong answer is worse.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from enum import StrEnum
from types import CodeType
from typing import TYPE_CHECKING, Any

from protean.ir.analysis.source_provider import SourceProvider
from protean.utils import DomainObjects

if TYPE_CHECKING:
    from protean.domain import Domain

#: A method body node, sync or async. Every check against one of these must
#: admit both: Protean handlers are commonly ``async def``, and matching only
#: ``ast.FunctionDef`` silently yields an empty method map for them.
FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef

#: Node kinds that can contain a statement. Descending only into these keeps
#: the walk off every expression node in the tree: it is ~50x less work, and it
#: bounds recursion by statement nesting rather than by expression nesting,
#: where a long enough arithmetic expression would blow the stack.
_STATEMENT_NODES = (ast.stmt, ast.excepthandler, ast.match_case)


class MethodRole(StrEnum):
    """What a method *is*, where that follows from its element's type.

    A method carries at most one role, and only classes registered as domain
    elements carry roles at all. A helper class, or a method whose decorators
    say nothing on an element type with no undecorated role, is untagged.
    """

    COMMAND_HANDLER_METHOD = "COMMAND_HANDLER_METHOD"
    EVENT_HANDLER_METHOD = "EVENT_HANDLER_METHOD"
    PROJECTOR_ON_EVENT = "PROJECTOR_ON_EVENT"
    EVENT_APPLY = "EVENT_APPLY"
    AGGREGATE_BEHAVIOR = "AGGREGATE_BEHAVIOR"
    REPOSITORY_METHOD = "REPOSITORY_METHOD"


@dataclass(frozen=True, slots=True)
class MethodEntry:
    """One method of an indexed class."""

    name: str
    node: FunctionNode
    #: Trailing dotted segments of the method's decorators, in source order.
    #: Decorators that do not reduce to a plain name are absent.
    decorators: tuple[str, ...]

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<MethodEntry {self.name} line {self.node.lineno}>"


@dataclass(frozen=True, slots=True)
class ClassEntry:
    """One indexed class, with its methods."""

    module: str
    qualname: str
    node: ast.ClassDef
    _methods: dict[str, MethodEntry] = field(repr=False)

    @property
    def methods(self) -> tuple[MethodEntry, ...]:
        """The class's own methods, sorted by name.

        Functions written in the class body, including those under an ``if``
        or ``try`` in that body. A function nested inside a method, or in a
        class nested inside this one, is not a method of this class.
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
        self._element_types: dict[type, str] | None = None

    # ------------------------------------------------------------------
    # Package-wide access
    # ------------------------------------------------------------------

    def classes(self) -> tuple[ClassEntry, ...]:
        """Every class the package walk found, sorted by module then qualname.

        Whole-package scope: a class in a helper module that registers no
        element is indexed too. What the walk covers is the provider's
        business — the domain root's directory and its immediate
        subdirectories, minus modules that do not parse. Classes resolved on
        demand for an element outside the package are *not* reported here, so
        this stays a function of the package alone.
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

        Resolution is by ``(__module__, __qualname__)``, with the fallback for
        a rebuilt element's flattened qualname described in the module
        docstring. A class whose module has no source (built-in, dynamically
        created, not importable), whose qualname is not in that module's tree,
        or whose bare qualname matches several classes that its own methods
        cannot tell apart, yields ``None``.
        """
        # CPython guarantees a class's ``__qualname__`` is a string at
        # creation time, but both ``__module__`` and ``__qualname__`` are
        # ordinary attributes that code can reassign afterwards to anything.
        module = getattr(cls, "__module__", None)
        qualname = getattr(cls, "__qualname__", None)
        if not isinstance(module, str) or not isinstance(qualname, str) or not qualname:
            return None

        index = self._module_index(module)
        if "." in qualname:
            # A qualname that still carries its enclosing path was not
            # flattened, so it either matches exactly or names nothing.
            return index.get(qualname)

        candidates = [
            index[key] for key in sorted(index) if key.rsplit(".", 1)[-1] == qualname
        ]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            return None
        written = _written_qualname(cls)
        return index.get(written) if written is not None else None

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
        source is unavailable or ambiguous, the method is not written in the
        class body, or nothing about the element's type and the method's
        decorators names a role.

        A leading underscore keeps a method out of the two name-derived roles
        (aggregate behavior, repository method) but not out of the four
        decorator-derived ones: ``@handle`` on ``_secret`` is still a handler
        method, because Protean registers it as one.
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
        """Every method of ``cls`` that carries a role, name -> role.

        In method-name order, so two runs over the same source produce the same
        mapping in the same order.
        """
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
        """Index every module the provider finds on disk. Runs once.

        The "runs once" flag is set only after the walk has populated the
        index. Setting it first would be a re-entrancy guard that answers a
        concurrent caller with an empty index instead of blocking it — this
        class is single-threaded by contract, and it should fail loudly rather
        than quietly if that contract is broken.
        """
        if self._walked:
            return
        names = []
        for module, tree in self._provider.iter_trees():
            self._modules[module] = _index_tree(module, tree)
            names.append(module)
        self._package_modules = tuple(names)
        self._walked = True

    def _element_type(self, cls: type) -> str | None:
        """The registered ``DomainObjects`` value for a class, or ``None``.

        Framework-internal elements are excluded: they are Protean's own
        machinery, not the user's domain, and tagging their methods as domain
        roles would put framework code in a rule's findings.
        """
        if self._element_types is None:
            self._element_types = _registered_element_types(self._domain)
        try:
            return self._element_types.get(cls)
        except TypeError:  # pragma: no cover - a class with an unusable __hash__
            return None


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def _registered_element_types(domain: Domain) -> dict[type, str]:
    """Map each registered element class to its element type.

    Keyed by the class object itself: registration hands the caller back the
    class it registered, so object identity holds even where Protean rebuilds
    an element via ``type()``. The name pair does *not* survive that rebuild,
    which is exactly why it is not the key here.
    """
    types: dict[type, str] = {}
    for element_type, records in domain._domain_registry._elements.items():
        for record in records.values():
            if record.internal:
                continue
            try:
                # First registration wins, for the same reason the class index
                # takes the first definition: a stable answer.
                types.setdefault(record.cls, element_type)
            except TypeError:  # pragma: no cover - unhashable metaclass
                continue
    return types


def _written_qualname(cls: type) -> str | None:
    """The qualname a class was written under, read off its own functions.

    ``co_qualname`` is the path the compiler recorded for a function, enclosing
    classes and ``<locals>`` segments included, and it survives the ``type()``
    rebuild that flattens the class's own ``__qualname__``. Only functions whose
    parent segment is this class's name get a vote, so something the framework
    attached to the class does not drag the answer elsewhere. Anything short of
    one unanimous answer is ``None``.
    """
    parents = set()
    for value in vars(cls).values():
        code = _code_of(value)
        if code is None or "." not in code.co_qualname:
            continue
        parent = code.co_qualname.rpartition(".")[0]
        if parent.rsplit(".", 1)[-1] == cls.__name__:
            parents.add(parent)
    return parents.pop() if len(parents) == 1 else None


def _code_of(value: Any) -> CodeType | None:
    """The code object behind a class attribute, through the usual wrappers."""
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    elif isinstance(value, property):
        value = value.fget
    # ``@functools.wraps`` (``invariant.pre``/``post``, and user decorators)
    # hides the written function behind ``__wrapped__``. Walked with a seen-set
    # so a self-referential chain cannot spin.
    seen: set[int] = set()
    while True:
        wrapped = getattr(value, "__wrapped__", None)
        if wrapped is None or id(wrapped) in seen:
            break
        seen.add(id(wrapped))
        value = wrapped
    code = getattr(value, "__code__", None)
    return code if isinstance(code, CodeType) else None


def _index_tree(module: str, tree: ast.Module) -> dict[str, ClassEntry]:
    """Index every class in one module tree, keyed by qualname."""
    entries: dict[str, ClassEntry] = {}

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, _STATEMENT_NODES):
                # An expression cannot contain a class or a function body.
                continue
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
                # Classes hide inside ``if``/``try``/``with``/``match`` bodies.
                walk(child, prefix)

    walk(tree, "")
    return entries


def _class_methods(node: ast.ClassDef) -> dict[str, MethodEntry]:
    """The functions written in a class body, first definition winning.

    Descends through the statements wrapping part of a class body — an ``if
    TYPE_CHECKING:``, a ``try``/``except`` around an optional implementation —
    because those methods are as much in the body as any other. Does not
    descend into a nested class or into a method: those functions belong to
    something else.
    """
    methods: dict[str, MethodEntry] = {}

    def collect(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if not isinstance(child, _STATEMENT_NODES):
                continue
            if isinstance(child, FunctionNode):
                if child.name not in methods:
                    methods[child.name] = MethodEntry(
                        child.name, child, _decorator_names(child)
                    )
            elif not isinstance(child, ast.ClassDef):
                collect(child)

    collect(node)
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


#: Decorator names that mark a handler method. ``on`` is a literal alias of
#: ``handle`` (``protean.core.projector``), so it reads the same way wherever
#: it is written, projector or not.
_HANDLES = frozenset({"handle", "on"})
_APPLY = "apply"

#: Trailing decorator segments that say a public method is something other than
#: plain behavior, so the name-derived roles stand back rather than mislabel it.
#: ``pre``/``post`` are what ``@invariant.pre``/``@invariant.post`` reduce to,
#: ``setter``/``deleter`` what a property's companions reduce to.
_NOT_PLAIN_BEHAVIOR = frozenset(
    {
        "invariant",
        "pre",
        "post",
        "property",
        "cached_property",
        "setter",
        "deleter",
        "staticmethod",
        "classmethod",
    }
)


def _role(element_type: str, method: MethodEntry) -> MethodRole | None:
    """Derive a method's role from its element type and its decorators."""
    decorators = method.decorators
    # A name-derived role needs a public name and a body that no decorator
    # claims for something else.
    plain = not method.name.startswith("_") and not _NOT_PLAIN_BEHAVIOR.intersection(
        decorators
    )

    handles = bool(_HANDLES.intersection(decorators))

    if element_type == DomainObjects.COMMAND_HANDLER.value:
        if handles:
            return MethodRole.COMMAND_HANDLER_METHOD
        return None

    if element_type in (
        DomainObjects.EVENT_HANDLER.value,
        DomainObjects.PROCESS_MANAGER.value,
    ):
        if handles:
            return MethodRole.EVENT_HANDLER_METHOD
        return None

    if element_type == DomainObjects.PROJECTOR.value:
        if handles:
            return MethodRole.PROJECTOR_ON_EVENT
        return None

    if element_type == DomainObjects.AGGREGATE.value:
        # ``@apply`` first: an apply method is an event application, not a
        # behavior, even though it is public and undecorated-looking otherwise.
        if _APPLY in decorators:
            return MethodRole.EVENT_APPLY
        if plain:
            return MethodRole.AGGREGATE_BEHAVIOR
        return None

    if element_type in (
        DomainObjects.REPOSITORY.value,
        DomainObjects.EVENT_SOURCED_REPOSITORY.value,
    ):
        if plain:
            return MethodRole.REPOSITORY_METHOD
        return None

    return None
