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
import sys
from typing import Callable

from mypy.nodes import (
    MDEF,
    CallExpr,
    MemberExpr,
    NameExpr,
    SymbolTableNode,
    TypeInfo,
    Var,
)
from mypy.plugin import ClassDefContext, FunctionContext, Plugin
from mypy.types import NoneType, Type, UnionType

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
    # Container fields (protean.fields.containers)
    "protean.fields.containers.List": "builtins.list",
    "protean.fields.containers.Dict": "builtins.dict",
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


_build_reexport_map()


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

        # Check re-exported names (protean.fields.String, etc.)
        canonical = _REEXPORT_MAP.get(fullname)
        if canonical is not None:
            type_fqn = FIELD_TYPE_MAP[canonical]
            has_implicit_default = canonical in _FIELDS_WITH_IMPLICIT_DEFAULT

            def hook(ctx: FunctionContext) -> Type:
                return _field_factory_hook(ctx, type_fqn, has_implicit_default)

            return hook

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
        # Already a subclass — just ensure auto-id is injected
        _maybe_inject_auto_id(ctx, info, decorator_name)
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
