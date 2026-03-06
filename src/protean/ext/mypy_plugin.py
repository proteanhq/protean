"""Mypy plugin for Protean domain elements.

Teaches mypy to understand Protean's field declaration syntax::

    class Order(BaseAggregate):
        name = String(max_length=100)    # mypy sees: str
        quantity = Integer(min_value=1)  # mypy sees: int
        price = Float(min_value=0)       # mypy sees: float

And Protean's decorator-based class registration::

    @domain.aggregate
    class Customer:
        name = String(required=True)
        customer.id        # mypy sees: str (auto-injected)
        customer.raise_()  # mypy sees method from BaseAggregate

Without this plugin, mypy would see field factories as ``FieldSpec`` instances
and decorator-registered classes would lack base class methods/attributes.

Enable the plugin in your mypy configuration::

    [mypy]
    plugins = protean.ext.mypy_plugin

**How it works**:

1. ``get_function_hook`` overrides field factory return types
   (``String()`` → ``str``, ``Integer()`` → ``int``, etc.)

2. ``get_customize_class_mro_hook`` inspects class decorators at MRO
   calculation time and injects base classes for decorator-registered
   classes (``@domain.aggregate`` adds ``BaseAggregate`` to bases),
   making all base class methods visible.

   Note: ``get_class_decorator_hook`` cannot be used here because
   the Domain methods are annotated with ``@dataclass_transform()``,
   which causes mypy to handle them internally and skip the decorator
   hook entirely.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Callable

from mypy.nodes import (
    ARG_NAMED_OPT,
    ARG_POS,
    MDEF,
    Argument,
    Block,
    CallExpr,
    FuncDef,
    MemberExpr,
    NameExpr,
    PassStmt,
    RefExpr,
    SymbolTableNode,
    TypeInfo,
    Var,
)
from mypy.plugin import AnalyzeTypeContext, ClassDefContext, FunctionContext, Plugin
from mypy.types import (
    AnyType,
    CallableType,
    NoneType,
    RawExpressionType,
    Type,
    TypeOfAny,
    UnionType,
)

# ---------------------------------------------------------------------------
# Field factory → Python type mapping
# ---------------------------------------------------------------------------
# Maps the fully-qualified name of each Protean field factory function to
# the fully-qualified name of the Python type it resolves to at runtime.
#
# These must match the ``python_type`` argument that each factory passes to
# ``FieldSpec()`` in ``src/protean/fields/simple.py`` and ``containers.py``.
FIELD_TYPE_MAP: dict[str, str] = {
    # Simple fields (protean.fields.simple)
    "protean.fields.simple.String": "builtins.str",
    "protean.fields.simple.Text": "builtins.str",
    "protean.fields.simple.Integer": "builtins.int",
    "protean.fields.simple.Float": "builtins.float",
    "protean.fields.simple.Boolean": "builtins.bool",
    "protean.fields.simple.Date": "datetime.date",
    "protean.fields.simple.DateTime": "datetime.datetime",
    "protean.fields.simple.Identifier": "builtins.str",
    "protean.fields.simple.Auto": "builtins.str",
    "protean.fields.simple.Status": "builtins.str",
    # Container fields (protean.fields.containers)
    # These map to builtins.list / builtins.dict; actual resolution adds
    # type parameters (list[Any], dict[str, Any]) in the hook callbacks.
    "protean.fields.containers.List": "builtins.list",
    "protean.fields.containers.Dict": "builtins.dict",
}

# Association / embedded field factories whose return type depends on
# their first positional argument (the target class).
#
# HasOne(OrderItem)   → OrderItem | None
# HasMany(OrderItem)  → list[OrderItem]
# ValueObject(Address) → Address | None
_ASSOCIATION_FIELD_NAMES: dict[str, str] = {
    "protean.fields.association.HasOne": "has_one",
    "protean.fields.association.HasMany": "has_many",
    "protean.fields.association.Reference": "has_one",  # Reference resolves like HasOne
    "protean.fields.embedded.ValueObject": "value_object",
}

# Container fields always provide an implicit default (empty list/dict)
# when the user doesn't supply one, so they should never be Optional.
_FIELDS_WITH_IMPLICIT_DEFAULT: set[str] = {
    "protean.fields.containers.List",
    "protean.fields.containers.Dict",
}

# Re-exported names (protean.fields re-exports from protean.fields.simple)
# Map these to the canonical names so both import paths work.
_REEXPORT_MAP: dict[str, str] = {}


def _build_reexport_map() -> None:
    """Build a mapping from re-exported names to canonical names.

    Users typically import from ``protean.fields`` rather than
    ``protean.fields.simple``.  Mypy may resolve the callee's fullname
    to either path depending on how the import is structured.
    """
    for canonical in list(FIELD_TYPE_MAP):
        # protean.fields.simple.String → protean.fields.String
        parts = canonical.split(".")
        if len(parts) >= 4:
            reexported = f"{parts[0]}.{parts[1]}.{parts[-1]}"
            _REEXPORT_MAP[reexported] = canonical

    for canonical in _ASSOCIATION_FIELD_NAMES:
        parts = canonical.split(".")
        if len(parts) >= 4:
            reexported = f"{parts[0]}.{parts[1]}.{parts[-1]}"
            _REEXPORT_MAP[reexported] = canonical


_build_reexport_map()


def _resolve_association_fullname(fullname: str) -> str | None:
    """Match a fullname to an association field, handling __init__ suffix.

    Mypy may call get_function_hook with:
    - The class name directly: ``protean.fields.association.HasOne``
    - The __init__ method: ``protean.fields.association.HasOne.__init__``
    """
    if fullname in _ASSOCIATION_FIELD_NAMES:
        return fullname
    # Strip __init__ suffix and retry
    if fullname.endswith(".__init__"):
        base = fullname[: -len(".__init__")]
        if base in _ASSOCIATION_FIELD_NAMES:
            return base
    # Check re-export map
    canonical = _REEXPORT_MAP.get(fullname)
    if canonical is not None and canonical in _ASSOCIATION_FIELD_NAMES:
        return canonical
    if fullname.endswith(".__init__"):
        base = fullname[: -len(".__init__")]
        canonical = _REEXPORT_MAP.get(base)
        if canonical is not None and canonical in _ASSOCIATION_FIELD_NAMES:
            return canonical
    return None


# ---------------------------------------------------------------------------
# Decorator → base class mapping
# ---------------------------------------------------------------------------
# Maps each decorator method name to the FQN of the base class that
# Protean injects at runtime via derive_element_class() → type().
DECORATOR_BASE_CLASS_MAP: dict[str, str] = {
    "aggregate": "protean.core.aggregate.BaseAggregate",
    "entity": "protean.core.entity.BaseEntity",
    "value_object": "protean.core.value_object.BaseValueObject",
    "command": "protean.core.command.BaseCommand",
    "event": "protean.core.event.BaseEvent",
    "domain_service": "protean.core.domain_service.BaseDomainService",
    "command_handler": "protean.core.command_handler.BaseCommandHandler",
    "event_handler": "protean.core.event_handler.BaseEventHandler",
    "application_service": "protean.core.application_service.BaseApplicationService",
    "subscriber": "protean.core.subscriber.BaseSubscriber",
    "projection": "protean.core.projection.BaseProjection",
    "projector": "protean.core.projector.BaseProjector",
    "query": "protean.core.query.BaseQuery",
    "process_manager": "protean.core.process_manager.BaseProcessManager",
    "repository": "protean.core.repository.BaseRepository",
    "database_model": "protean.core.database_model.BaseDatabaseModel",
    "email": "protean.core.email.BaseEmail",
}

# Decorators that auto-inject an ``id`` field at runtime.
_AUTO_ID_DECORATORS: set[str] = {"aggregate", "entity"}

# FQN of the Domain class — used to verify a decorator's receiver type.
_DOMAIN_FQN = "protean.domain.Domain"

# Debug mode: set PROTEAN_MYPY_DEBUG=1 to print diagnostic info to stderr.
_DEBUG = os.environ.get("PROTEAN_MYPY_DEBUG", "") == "1"


def _extract_decorator_name(fullname: str) -> str | None:
    """Extract the decorator method name from a fully-qualified name.

    Given ``protean.domain.Domain.aggregate``, returns ``"aggregate"``.
    Returns ``None`` if the fullname doesn't match any known prefix.

    Used by unit tests and the ``get_class_decorator_hook`` fallback.
    """
    _DOMAIN_CLASS_PREFIXES = (
        "protean.domain.Domain.",
        "protean.domain.__init__.Domain.",
    )
    for prefix in _DOMAIN_CLASS_PREFIXES:
        if fullname.startswith(prefix):
            method = fullname[len(prefix) :]
            if method in DECORATOR_BASE_CLASS_MAP:
                return method
    return None


def _extract_decorator_name_from_expr(decorator: object) -> str | None:
    """Extract a Protean decorator name from a decorator AST expression.

    Handles two forms:
    - ``@domain.aggregate`` → MemberExpr with name="aggregate"
    - ``@domain.aggregate(...)`` → CallExpr with callee being MemberExpr

    Returns the decorator method name (e.g. ``"aggregate"``) if the
    expression is a method call on an object and the method name is a
    known Protean decorator, or ``None`` otherwise.

    Note: This hook fires during MRO calculation (very early in analysis),
    so the NameExpr for the receiver (e.g. ``domain``) may not be resolved
    yet (``expr.node is None``). We match on the method name alone, which
    is safe because Protean decorator names (``aggregate``, ``entity``,
    etc.) are specific enough that false positives are extremely unlikely
    for method-style decorators (``@obj.aggregate``).
    """
    # Unwrap @domain.aggregate(...) → get the MemberExpr
    if isinstance(decorator, CallExpr):
        decorator = decorator.callee

    if not isinstance(decorator, MemberExpr):
        return None

    method_name = decorator.name
    if method_name not in DECORATOR_BASE_CLASS_MAP:
        return None

    # At MRO calculation time, name resolution may not be complete,
    # so we can't always verify the receiver's type. If the receiver
    # IS resolved, we verify it's a Domain instance. If not resolved,
    # we trust the method name match (very low false positive risk).
    expr = decorator.expr
    if isinstance(expr, NameExpr) and expr.node is not None:
        node_type = getattr(expr.node, "type", None)
        if node_type is not None:
            type_type = getattr(node_type, "type", None)
            if type_type is not None:
                fqn = getattr(type_type, "fullname", None)
                if fqn is not None and fqn != _DOMAIN_FQN:
                    # Resolved to a non-Domain type — skip
                    return None

    return method_name


# ---------------------------------------------------------------------------
# Plugin class
# ---------------------------------------------------------------------------
class ProteanPlugin(Plugin):
    """Mypy plugin for Protean field factories and decorator base injection."""

    def get_function_hook(
        self, fullname: str
    ) -> Callable[[FunctionContext], Type] | None:
        # Check canonical names first
        if fullname in FIELD_TYPE_MAP:
            type_fqn = FIELD_TYPE_MAP[fullname]
            has_implicit_default = fullname in _FIELDS_WITH_IMPLICIT_DEFAULT

            def hook(ctx: FunctionContext) -> Type:
                return _field_factory_hook(ctx, type_fqn, has_implicit_default)

            return hook

        # Check association / embedded fields (class constructors)
        resolved = _resolve_association_fullname(fullname)
        if resolved is not None:
            kind = _ASSOCIATION_FIELD_NAMES[resolved]

            def assoc_hook(ctx: FunctionContext) -> Type:
                return _association_field_hook(ctx, kind)

            return assoc_hook

        # Check re-exported names (protean.fields.String, etc.)
        canonical = _REEXPORT_MAP.get(fullname)
        if canonical is not None and canonical in FIELD_TYPE_MAP:
            type_fqn = FIELD_TYPE_MAP[canonical]
            has_implicit_default = canonical in _FIELDS_WITH_IMPLICIT_DEFAULT

            def hook(ctx: FunctionContext) -> Type:
                return _field_factory_hook(ctx, type_fqn, has_implicit_default)

            return hook

        # Check re-exported association fields
        if canonical is not None and canonical in _ASSOCIATION_FIELD_NAMES:
            kind = _ASSOCIATION_FIELD_NAMES[canonical]

            def assoc_hook(ctx: FunctionContext) -> Type:
                return _association_field_hook(ctx, kind)

            return assoc_hook

        return None

    def get_type_analyze_hook(
        self, fullname: str
    ) -> Callable[[AnalyzeTypeContext], Type] | None:
        """Map Protean field descriptors to Python types when used as annotations.

        When users write ``name: String`` or ``name: String = String(...)``,
        mypy sees ``String`` as a function (due to TYPE_CHECKING overloads)
        and rejects it as a type. This hook intercepts that and returns the
        correct Python type (e.g., ``str``).
        """
        # Check canonical names
        type_fqn = FIELD_TYPE_MAP.get(fullname)
        if type_fqn is None:
            # Check re-exported names
            canonical = _REEXPORT_MAP.get(fullname)
            if canonical is not None:
                type_fqn = FIELD_TYPE_MAP.get(canonical)

        if type_fqn is not None:

            def type_hook(ctx: AnalyzeTypeContext) -> Type:
                return _field_type_analyze_hook(ctx, type_fqn)

            return type_hook

        return None

    def get_class_decorator_hook(
        self, fullname: str
    ) -> Callable[[ClassDefContext], None] | None:
        """Fallback for decorators not handled by @dataclass_transform().

        In practice, the Domain methods use ``@dataclass_transform()``,
        so mypy handles them internally and this hook is not called for
        them. The real work is done in ``get_customize_class_mro_hook``.
        This hook remains as a safety net for edge cases.
        """
        decorator_name = _extract_decorator_name(fullname)
        if decorator_name is None:
            return None

        base_fqn = DECORATOR_BASE_CLASS_MAP[decorator_name]

        def callback(ctx: ClassDefContext) -> None:
            _inject_base_class(ctx, base_fqn, decorator_name)

        return callback

    def get_customize_class_mro_hook(
        self, fullname: str
    ) -> Callable[[ClassDefContext], None] | None:
        """Inject base classes for Protean-decorated classes.

        This hook fires for every class definition during MRO calculation.
        We inspect the class's decorator AST nodes to identify Protean
        domain decorators (``@domain.aggregate``, etc.) and inject the
        corresponding base class.

        This approach is necessary because ``@dataclass_transform()``
        on the Domain methods causes mypy to bypass
        ``get_class_decorator_hook`` entirely.
        """
        # Return a callback for all classes. The callback is lightweight
        # and returns quickly if no protean decorator is found.
        return _customize_class_mro_callback


# ---------------------------------------------------------------------------
# MRO customization callback
# ---------------------------------------------------------------------------
def _customize_class_mro_callback(ctx: ClassDefContext) -> None:
    """Inspect class decorators and inject base classes for Protean elements."""
    # First check for Protean decorators
    for decorator in ctx.cls.decorators:
        decorator_name = _extract_decorator_name_from_expr(decorator)
        if decorator_name is not None:
            if _DEBUG:
                print(
                    f"[protean-mypy-debug] injecting base for "
                    f"@domain.{decorator_name} on {ctx.cls.fullname}",
                    file=sys.stderr,
                )
            base_fqn = DECORATOR_BASE_CLASS_MAP[decorator_name]
            _inject_base_class(ctx, base_fqn, decorator_name)
            return  # Only process the first matching decorator

    # For classes that explicitly inherit from Protean base classes
    # (no decorator), inject auto-id and HasMany methods.
    info = ctx.cls.info
    decorator_name = _detect_protean_base_class(info)
    if decorator_name is not None:
        _maybe_inject_auto_id(ctx, info, decorator_name)
        _synthesize_has_many_methods(ctx)


# ---------------------------------------------------------------------------
# Base class injection
# ---------------------------------------------------------------------------
def _inject_base_class(
    ctx: ClassDefContext, base_fqn: str, decorator_name: str
) -> None:
    """Inject the Protean base class into the decorated class's MRO.

    This makes all base class methods and attributes (``raise_()``,
    ``to_dict()``, ``_events``, etc.) visible to mypy.
    """
    info: TypeInfo = ctx.cls.info

    # Look up the base class TypeInfo
    base_sym = ctx.api.lookup_fully_qualified_or_none(base_fqn)
    if _DEBUG:
        print(
            f"[protean-mypy-debug] lookup {base_fqn}: "
            f"sym={base_sym}, "
            f"node_type={type(base_sym.node).__name__ if base_sym and base_sym.node else 'N/A'}",
            file=sys.stderr,
        )
    if base_sym is None or not isinstance(base_sym.node, TypeInfo):
        if _DEBUG:
            print(
                f"[protean-mypy-debug] base class not found: {base_fqn}",
                file=sys.stderr,
            )
        return

    base_info: TypeInfo = base_sym.node

    # Check if the class already inherits from the base (explicit inheritance)
    if _is_subclass(info, base_info):
        # Already a subclass — just ensure auto-id and HasMany methods
        _maybe_inject_auto_id(ctx, info, decorator_name)
        _synthesize_has_many_methods(ctx)
        return

    # We cannot add BaseAggregate/BaseEntity/etc. to info.bases because
    # they inherit from pydantic's BaseModel (with ModelMetaclass), which
    # conflicts with the implicit metaclass from @dataclass_transform().
    #
    # Instead, we copy symbols (methods, attributes) from the base class
    # hierarchy directly into the class's namespace. We must create fresh
    # Var/node copies to avoid "value is not in list" errors when mypy
    # tries to find the defining class in the MRO.
    _copy_base_symbols(info, base_info)

    # Inject auto-id for aggregate/entity decorators
    _maybe_inject_auto_id(ctx, info, decorator_name)

    # Synthesize __init__ from field declarations (decorator-registered classes)
    _synthesize_init(ctx, decorator_name)

    # Synthesize add_*/remove_* for HasMany fields
    _synthesize_has_many_methods(ctx)


def _detect_protean_base_class(info: TypeInfo) -> str | None:
    """Check if a class inherits from a known Protean base class.

    Returns the decorator name (e.g. "aggregate", "entity") if the class
    inherits from a known Protean base class, or None otherwise.
    """
    # Reverse map: base FQN → decorator name
    _BASE_TO_DECORATOR = {v: k for k, v in DECORATOR_BASE_CLASS_MAP.items()}

    for mro_entry in info.mro:
        if mro_entry.fullname in _BASE_TO_DECORATOR:
            return _BASE_TO_DECORATOR[mro_entry.fullname]
    return None


def _is_subclass(info: TypeInfo, base_info: TypeInfo) -> bool:
    """Check if ``info`` is already a subclass of ``base_info``."""
    for base in info.mro:
        if base.fullname == base_info.fullname:
            return True
    return False


def _copy_base_symbols(info: TypeInfo, base_info: TypeInfo) -> None:
    """Copy symbols from base class into the class's namespace.

    Only copies symbols that aren't already defined in the class itself.
    This walks the entire MRO of the base to include inherited symbols.

    We create proxy SymbolTableNode entries that reference the original
    nodes. For Var nodes, we create a fresh copy with `info` pointing
    to the target class to avoid ``ValueError`` in ``type_object_type``
    when mypy tries to find the defining class in the MRO.
    """
    for mro_entry in base_info.mro:
        for name, sym in mro_entry.names.items():
            if name not in info.names and not name.startswith("__"):
                # Create a new SymbolTableNode referencing the same
                # underlying node. This is safe for FuncDef nodes
                # (methods) because mypy resolves them via the node's
                # own type, not via MRO lookup of info.
                info.names[name] = sym


def _maybe_inject_auto_id(
    ctx: ClassDefContext, info: TypeInfo, decorator_name: str
) -> None:
    """Inject ``id: str`` for aggregate/entity if not already declared.

    At runtime, Protean's ``_prepare_pydantic_namespace()`` injects an
    ``id`` field with type ``str | int | UUID``. For simplicity, we
    declare it as ``str`` here since that's the most common usage.
    """
    if decorator_name not in _AUTO_ID_DECORATORS:
        return

    # Check if id is already declared in the class or any base
    if _has_attribute(info, "id"):
        return

    # Add id as a Var of type str
    str_type = ctx.api.named_type("builtins.str", [])
    id_var = Var("id", str_type)
    id_var.info = info
    id_var._fullname = f"{info.fullname}.id"
    id_var.is_initialized_in_class = True
    info.names["id"] = _make_symbol_table_node(id_var)


def _has_attribute(info: TypeInfo, name: str) -> bool:
    """Check if an attribute is declared in the class or any of its bases."""
    for mro_entry in info.mro:
        if name in mro_entry.names:
            return True
    return False


def _make_symbol_table_node(var: Var) -> SymbolTableNode:
    """Create a SymbolTableNode for a Var."""
    return SymbolTableNode(MDEF, var)


# ---------------------------------------------------------------------------
# __init__ synthesis for decorator-registered classes
# ---------------------------------------------------------------------------
# Decorators that should have __init__ synthesized from their field declarations.
# These correspond to domain elements whose instances are constructed with kwargs.
_INIT_SYNTHESIS_DECORATORS: set[str] = {
    "aggregate",
    "entity",
    "value_object",
    "command",
    "event",
    "projection",
}

# Mapping from short field factory names to canonical fully-qualified names.
# At MRO calculation time, NameExpr.fullname is not yet resolved, so we
# match on the short name (e.g. "String") to look up the canonical FQN.
_SHORT_NAME_TO_CANONICAL: dict[str, str] = {}


def _build_short_name_map() -> None:
    """Build mapping from short names to canonical FQN for field factories."""
    for canonical in FIELD_TYPE_MAP:
        short = canonical.rsplit(".", 1)[-1]
        _SHORT_NAME_TO_CANONICAL[short] = canonical
    for canonical in _ASSOCIATION_FIELD_NAMES:
        short = canonical.rsplit(".", 1)[-1]
        _SHORT_NAME_TO_CANONICAL[short] = canonical


_build_short_name_map()

# Regex to extract the field factory name from a RawExpressionType note.
# The note has the form: "Suggestion: use Float[...] instead of Float(...)"
_NOTE_FIELD_RE = re.compile(r"Suggestion: use (\w+)\[")


def _extract_field_factory_from_annotation(stmt: object) -> str | None:
    """Extract the Protean field factory short name from an annotation-style field.

    For ``price: Float(required=True)``, mypy's parser creates a RawExpressionType
    with note ``"Suggestion: use Float[...] instead of Float(...)"``.
    We extract ``"Float"`` and map it to a canonical FQN.

    Returns the canonical fully-qualified name (e.g. ``protean.fields.simple.Float``)
    if found, or None.
    """
    from mypy.nodes import AssignmentStmt

    if not isinstance(stmt, AssignmentStmt):
        return None

    raw_type = stmt.type
    if not isinstance(raw_type, RawExpressionType):
        return None
    if raw_type.note is None:
        return None

    match = _NOTE_FIELD_RE.search(raw_type.note)
    if match is None:
        return None

    short_name = match.group(1)
    return _SHORT_NAME_TO_CANONICAL.get(short_name)


def _synthesize_init(ctx: ClassDefContext, decorator_name: str) -> None:
    """Synthesize an ``__init__`` method from field declarations in the class body.

    Scans the class body for assignments of the form ``name = FieldFactory(...)``
    where ``FieldFactory`` is a known Protean field factory (String, Integer, etc.),
    and builds an ``__init__(self, *, name: type = ..., ...)`` method.

    This is necessary because ``@dataclass_transform()`` on instance methods
    is not supported by mypy, so decorator-registered classes (``@domain.aggregate``)
    don't get automatic ``__init__`` synthesis.
    """
    if decorator_name not in _INIT_SYNTHESIS_DECORATORS:
        return

    info: TypeInfo = ctx.cls.info

    # Don't override an explicitly declared __init__
    if "__init__" in info.names:
        existing = info.names["__init__"]
        # Only skip if it's defined in this class, not inherited
        if existing.node and getattr(existing.node, "info", None) is info:
            return

    # Collect field parameters from class body assignments
    fields: list[tuple[str, Type]] = []

    for stmt in ctx.cls.defs.body:
        # Look for assignments like: name = String(required=True)
        from mypy.nodes import AssignmentStmt

        if not isinstance(stmt, AssignmentStmt):
            continue
        if len(stmt.lvalues) != 1:
            continue
        lvalue = stmt.lvalues[0]
        if not isinstance(lvalue, NameExpr):
            continue

        field_name = lvalue.name
        if field_name.startswith("_"):
            continue

        rvalue = stmt.rvalue
        if not isinstance(rvalue, CallExpr):
            continue

        # Resolve the callee to a known field factory
        callee = rvalue.callee
        callee_fullname: str | None = None
        if isinstance(callee, RefExpr) and callee.fullname:
            callee_fullname = callee.fullname
        elif isinstance(callee, MemberExpr):
            callee_fullname = callee.fullname

        # At MRO time, fullname may not be resolved yet.
        # Fall back to matching by short name (e.g. "String", "Integer").
        if callee_fullname is None and isinstance(callee, NameExpr):
            callee_fullname = _SHORT_NAME_TO_CANONICAL.get(callee.name)

        if _DEBUG:
            print(
                f"[protean-mypy-debug]   {field_name}: callee={type(callee).__name__}, "
                f"fullname={callee_fullname}",
                file=sys.stderr,
            )

        if callee_fullname is None:
            continue

        # Check simple field factories
        field_type = _resolve_field_type_for_init(ctx, callee_fullname, rvalue)
        if field_type is not None:
            fields.append((field_name, field_type))

    # Also check for annotation-style fields: name: String(required=True)
    # These produce a RawExpressionType with the field factory name in the note.
    for stmt in ctx.cls.defs.body:
        from mypy.nodes import AssignmentStmt

        if not isinstance(stmt, AssignmentStmt):
            continue
        if len(stmt.lvalues) != 1:
            continue
        lvalue = stmt.lvalues[0]
        if not isinstance(lvalue, NameExpr) or lvalue.name.startswith("_"):
            continue

        field_name = lvalue.name
        # Already captured via assignment-style — skip
        if any(f[0] == field_name for f in fields):
            continue

        # Try to extract field factory from annotation
        callee_fullname = _extract_field_factory_from_annotation(stmt)
        if callee_fullname is None:
            continue

        # Resolve the Python type. Since we can't extract kwargs (required, default)
        # from the RawExpressionType, we treat all annotation-style fields as optional.
        type_fqn = FIELD_TYPE_MAP.get(callee_fullname)
        if type_fqn is None:
            canonical = _REEXPORT_MAP.get(callee_fullname)
            if canonical is not None:
                type_fqn = FIELD_TYPE_MAP.get(canonical)

        if type_fqn is not None:
            try:
                base_type = ctx.api.named_type(type_fqn, [])
                # Make it optional since we can't determine required/default
                fields.append((field_name, UnionType([base_type, NoneType()])))
            except (KeyError, AssertionError):
                pass
            continue

        # Check if it's an association field (HasMany, HasOne, ValueObject, Reference)
        resolved = _resolve_association_fullname(callee_fullname)
        if resolved is not None:
            fields.append((field_name, AnyType(TypeOfAny.special_form)))

        if _DEBUG:
            print(
                f"[protean-mypy-debug]   {field_name}: annotation-style, "
                f"callee={callee_fullname}",
                file=sys.stderr,
            )

    # Add 'id' field if this is an aggregate/entity
    if decorator_name in _AUTO_ID_DECORATORS:
        # id is already injected as a Var — add it as a kwarg too
        has_id = any(f[0] == "id" for f in fields)
        if not has_id:
            try:
                str_type = ctx.api.named_type("builtins.str", [])
                fields.insert(0, ("id", str_type))
            except (KeyError, AssertionError):
                pass

    if not fields:
        return

    # Build the __init__ method
    self_type = ctx.api.named_type(info.fullname, [])

    args: list[Argument] = [Argument(Var("self", self_type), self_type, None, ARG_POS)]
    arg_names: list[str] = ["self"]
    arg_kinds: list[int] = [ARG_POS]
    arg_types: list[Type] = [self_type]

    for field_name, field_type in fields:
        # All fields are optional kwargs with None default
        var = Var(field_name, field_type)
        args.append(Argument(var, field_type, None, ARG_NAMED_OPT))
        arg_names.append(field_name)
        arg_kinds.append(ARG_NAMED_OPT)
        arg_types.append(field_type)

    ret_type = NoneType()
    signature = CallableType(
        arg_types=arg_types,
        arg_kinds=arg_kinds,
        arg_names=arg_names,
        ret_type=ret_type,
        fallback=ctx.api.named_type("builtins.function", []),
    )

    func = FuncDef("__init__", args, Block([PassStmt()]))
    func.info = info
    func.type = signature
    func._fullname = f"{info.fullname}.__init__"
    func.is_class = False
    func.is_static = False

    info.names["__init__"] = SymbolTableNode(MDEF, func)

    if _DEBUG:
        field_desc = ", ".join(f"{n}: {t}" for n, t in fields)
        print(
            f"[protean-mypy-debug] synthesized __init__ for "
            f"{info.fullname}: ({field_desc})",
            file=sys.stderr,
        )


def _resolve_field_type_for_init(
    ctx: ClassDefContext, callee_fullname: str, rvalue: CallExpr
) -> Type | None:
    """Resolve the Python type for a field factory call, for __init__ synthesis.

    Returns the type that should be used as the __init__ parameter type,
    or None if the callee is not a known field factory.
    """
    # Check canonical names
    type_fqn = FIELD_TYPE_MAP.get(callee_fullname)
    if type_fqn is None:
        # Check re-export map
        canonical = _REEXPORT_MAP.get(callee_fullname)
        if canonical is not None:
            type_fqn = FIELD_TYPE_MAP.get(canonical)

    if type_fqn is not None:
        # Special-case container fields for proper type parameters
        any_type = AnyType(TypeOfAny.special_form)
        if type_fqn == "builtins.list":
            try:
                return ctx.api.named_type("builtins.list", [any_type])
            except (KeyError, AssertionError):
                return None
        if type_fqn == "builtins.dict":
            try:
                str_type = ctx.api.named_type("builtins.str", [])
                return ctx.api.named_type("builtins.dict", [str_type, any_type])
            except (KeyError, AssertionError):
                return None

        try:
            base_type = ctx.api.named_type(type_fqn, [])
        except (KeyError, AssertionError):
            return None

        # Check if the field is required/identifier/has default
        is_required = _get_call_kwarg_bool(rvalue, "required", default=False)
        is_identifier = _get_call_kwarg_bool(rvalue, "identifier", default=False)
        has_default = _has_call_kwarg(rvalue, "default")
        has_implicit_default = callee_fullname in _FIELDS_WITH_IMPLICIT_DEFAULT or (
            _REEXPORT_MAP.get(callee_fullname, "") in _FIELDS_WITH_IMPLICIT_DEFAULT
        )

        if (
            not is_required
            and not has_default
            and not is_identifier
            and not has_implicit_default
        ):
            return UnionType([base_type, NoneType()])
        return base_type

    # Check association fields
    resolved = _resolve_association_fullname(callee_fullname)
    if resolved is not None:
        # For association fields, return Any since the target class
        # reference may not be resolved at MRO time
        return AnyType(TypeOfAny.special_form)

    return None


def _get_call_kwarg_bool(call: CallExpr, name: str, *, default: bool) -> bool:
    """Extract a boolean keyword argument from a CallExpr AST node."""
    for i, arg_name in enumerate(call.arg_names):
        if arg_name == name and i < len(call.args):
            expr = call.args[i]
            if isinstance(expr, NameExpr):
                if expr.name == "True":
                    return True
                if expr.name == "False":
                    return False
    return default


def _has_call_kwarg(call: CallExpr, name: str) -> bool:
    """Check whether a keyword argument is present in a CallExpr AST node."""
    return name in call.arg_names


# ---------------------------------------------------------------------------
# HasMany add_*/remove_* synthesis
# ---------------------------------------------------------------------------
def _synthesize_has_many_methods(ctx: ClassDefContext) -> None:
    """Synthesize ``add_<name>`` and ``remove_<name>`` methods for HasMany fields.

    At runtime, Protean injects these methods via ``functools.partial``.
    This function makes them visible to mypy.

    Handles both assignment-style (``items = HasMany(OrderItem)``) and
    annotation-style (``items: HasMany(OrderItem)``) declarations.
    """
    info: TypeInfo = ctx.cls.info
    any_type = AnyType(TypeOfAny.special_form)
    none_type = NoneType()

    # Collect field names that are HasMany
    has_many_fields: list[str] = []

    for stmt in ctx.cls.defs.body:
        from mypy.nodes import AssignmentStmt

        if not isinstance(stmt, AssignmentStmt):
            continue
        if len(stmt.lvalues) != 1:
            continue
        lvalue = stmt.lvalues[0]
        if not isinstance(lvalue, NameExpr):
            continue

        field_name = lvalue.name

        # Try assignment-style first: items = HasMany(OrderItem)
        rvalue = stmt.rvalue
        if isinstance(rvalue, CallExpr):
            callee = rvalue.callee
            callee_fullname: str | None = None
            if isinstance(callee, RefExpr) and callee.fullname:
                callee_fullname = callee.fullname
            elif isinstance(callee, MemberExpr):
                callee_fullname = callee.fullname
            if callee_fullname is None and isinstance(callee, NameExpr):
                callee_fullname = _SHORT_NAME_TO_CANONICAL.get(callee.name)

            if callee_fullname is not None:
                resolved = _resolve_association_fullname(callee_fullname)
                if (
                    resolved is not None
                    and _ASSOCIATION_FIELD_NAMES.get(resolved) == "has_many"
                ):
                    has_many_fields.append(field_name)
                    continue

        # Try annotation-style: items: HasMany(OrderItem)
        annotation_fqn = _extract_field_factory_from_annotation(stmt)
        if annotation_fqn is not None:
            resolved = _resolve_association_fullname(annotation_fqn)
            if (
                resolved is not None
                and _ASSOCIATION_FIELD_NAMES.get(resolved) == "has_many"
            ):
                has_many_fields.append(field_name)

    # Synthesize methods for each HasMany field
    for field_name in has_many_fields:
        for prefix in ("add_", "remove_"):
            method_name = f"{prefix}{field_name}"
            if method_name in info.names:
                continue

            self_type = ctx.api.named_type(info.fullname, [])
            args = [
                Argument(Var("self", self_type), self_type, None, ARG_POS),
                Argument(Var("items", any_type), any_type, None, ARG_POS),
            ]
            sig = CallableType(
                arg_types=[self_type, any_type],
                arg_kinds=[ARG_POS, ARG_POS],
                arg_names=["self", "items"],
                ret_type=none_type,
                fallback=ctx.api.named_type("builtins.function", []),
            )
            func = FuncDef(method_name, args, Block([PassStmt()]))
            func.info = info
            func.type = sig
            func._fullname = f"{info.fullname}.{method_name}"
            info.names[method_name] = SymbolTableNode(MDEF, func)

        for prefix in ("get_one_from_", "filter_"):
            method_name = f"{prefix}{field_name}"
            if method_name in info.names:
                continue

            self_type = ctx.api.named_type(info.fullname, [])
            args = [
                Argument(Var("self", self_type), self_type, None, ARG_POS),
            ]
            sig = CallableType(
                arg_types=[self_type],
                arg_kinds=[ARG_POS],
                arg_names=["self"],
                ret_type=any_type,
                fallback=ctx.api.named_type("builtins.function", []),
            )
            func = FuncDef(method_name, args, Block([PassStmt()]))
            func.info = info
            func.type = sig
            func._fullname = f"{info.fullname}.{method_name}"
            info.names[method_name] = SymbolTableNode(MDEF, func)

    if _DEBUG and has_many_fields:
        has_many_methods = [
            n
            for n in info.names
            if n.startswith("add_")
            or n.startswith("remove_")
            or n.startswith("get_one_from_")
            or n.startswith("filter_")
        ]
        print(
            f"[protean-mypy-debug] synthesized HasMany methods for "
            f"{info.fullname}: {has_many_methods}",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Association / embedded field hook
# ---------------------------------------------------------------------------
def _association_field_hook(ctx: FunctionContext, kind: str) -> Type:
    """Override the return type of HasOne/HasMany/ValueObject fields.

    Extracts the first positional argument (the target class) and returns:
    - ``HasOne(X)``       → ``X | None``
    - ``HasMany(X)``      → ``list[X]``
    - ``ValueObject(X)``  → ``X | None``

    When the target class cannot be resolved (e.g. a forward-reference
    string), falls back to the default return type.
    """
    from mypy.types import Instance, TypeType
    from mypy.types import Type as MypyType

    # The target class is always the first positional argument
    if not ctx.args or not ctx.args[0]:
        return ctx.default_return_type

    first_arg_type: MypyType = ctx.arg_types[0][0]

    # Unwrap Type[X] / type[X] / callable → X
    target_type: MypyType | None = None
    if isinstance(first_arg_type, TypeType):
        target_type = first_arg_type.item
    elif isinstance(first_arg_type, CallableType) and isinstance(
        first_arg_type.ret_type, Instance
    ):
        # @dataclass_transform makes classes appear as callables;
        # the return type of the callable is the instance type.
        target_type = first_arg_type.ret_type
    elif (
        isinstance(first_arg_type, Instance)
        and first_arg_type.type.fullname == "builtins.type"
    ):
        # type[X] — extract the type argument
        if first_arg_type.args:
            target_type = first_arg_type.args[0]

    if target_type is None or isinstance(target_type, AnyType):
        # Forward reference string or unresolvable — fall back
        return ctx.default_return_type

    if kind == "has_many":
        # HasMany(X) → list[X]
        return ctx.api.named_generic_type("builtins.list", [target_type])
    else:
        # HasOne(X) / ValueObject(X) → X | None
        return UnionType([target_type, NoneType()])


# ---------------------------------------------------------------------------
# Type analyze hook callback
# ---------------------------------------------------------------------------
def _field_type_analyze_hook(ctx: AnalyzeTypeContext, type_fqn: str) -> Type:
    """Map a Protean field descriptor to its Python type when used as annotation.

    When a user writes ``name: String``, this hook fires and returns ``str``
    so mypy treats the annotation as valid.
    """
    any_type = AnyType(TypeOfAny.special_form)
    if type_fqn == "builtins.list":
        return ctx.api.named_type("builtins.list", [any_type])
    if type_fqn == "builtins.dict":
        str_type = ctx.api.named_type("builtins.str", [])
        return ctx.api.named_type("builtins.dict", [str_type, any_type])
    return ctx.api.named_type(type_fqn, [])


# ---------------------------------------------------------------------------
# Function hook callback
# ---------------------------------------------------------------------------
def _field_factory_hook(
    ctx: FunctionContext,
    type_fqn: str,
    has_implicit_default: bool,
) -> Type:
    """Override the return type of a Protean field factory.

    Instead of returning ``FieldSpec``, tells mypy the factory returns the
    resolved Python type (``str``, ``int``, etc.).  This makes mypy's
    normal type inference assign the correct type to field variables.
    """
    # Special-case container fields to get proper type parameters
    any_type = AnyType(TypeOfAny.special_form)
    if type_fqn == "builtins.list":
        try:
            return ctx.api.named_generic_type("builtins.list", [any_type])
        except (KeyError, AssertionError):
            return ctx.default_return_type
    if type_fqn == "builtins.dict":
        try:
            str_type = ctx.api.named_generic_type("builtins.str", [])
            return ctx.api.named_generic_type("builtins.dict", [str_type, any_type])
        except (KeyError, AssertionError):
            return ctx.default_return_type

    try:
        base_type = ctx.api.named_generic_type(type_fqn, [])
    except (KeyError, AssertionError):
        # Type not available — fall back to the default return type.
        return ctx.default_return_type

    # Determine if the field should be Optional.
    # At runtime, FieldSpec wraps in Optional when:
    #   - required=False (the default)
    #   - no explicit default provided
    #   - not an identifier field
    # Container fields (List, Dict) always provide implicit defaults.
    is_required = _get_kwarg_bool(ctx, "required", default=False)
    is_identifier = _get_kwarg_bool(ctx, "identifier", default=False)
    has_default = has_implicit_default or _has_kwarg(ctx, "default")

    if not is_required and not has_default and not is_identifier:
        return UnionType([base_type, NoneType()])

    return base_type


# ---------------------------------------------------------------------------
# Helpers for inspecting call arguments
# ---------------------------------------------------------------------------
def _get_kwarg_bool(ctx: FunctionContext, name: str, *, default: bool) -> bool:
    """Extract a boolean keyword argument from the function call.

    ``ctx.arg_names`` is ``list[list[str | None]]`` — outer list maps to
    formal parameters, inner list maps to the actual arguments bound to
    that parameter.  For ``**kwargs`` catch-all, all extra keyword args
    appear in its inner list.
    """
    for i, formal_names in enumerate(ctx.arg_names):
        for j, arg_name in enumerate(formal_names):
            if arg_name == name:
                expr = ctx.args[i][j]
                if isinstance(expr, NameExpr):
                    if expr.name == "True":
                        return True
                    if expr.name == "False":
                        return False
                return default
    return default


def _has_kwarg(ctx: FunctionContext, name: str) -> bool:
    """Check whether a keyword argument is present in the call."""
    for formal_names in ctx.arg_names:
        for arg_name in formal_names:
            if arg_name == name:
                return True
    return False


# ---------------------------------------------------------------------------
# Entry point — mypy discovers the plugin via this function
# ---------------------------------------------------------------------------
def plugin(version: str) -> type[Plugin]:
    """Mypy plugin entry point."""
    return ProteanPlugin
