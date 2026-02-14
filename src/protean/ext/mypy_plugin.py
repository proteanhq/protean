"""Mypy plugin for Protean domain elements.

Teaches mypy to understand Protean's field declaration syntax::

    class Order(BaseAggregate):
        name = String(max_length=100)    # mypy sees: str
        quantity = Integer(min_value=1)  # mypy sees: int
        price = Float(min_value=0)       # mypy sees: float

Without this plugin, mypy would see these fields as ``FieldSpec`` instances
rather than their resolved Python types.

Enable the plugin in your mypy configuration::

    [mypy]
    plugins = protean.ext.mypy_plugin

**How it works**: Uses ``get_function_hook`` to override the return type
of each field factory function (``String``, ``Integer``, etc.) at every
call site.  When mypy sees ``String(max_length=100)``, the plugin tells
it the call returns ``str`` instead of ``FieldSpec``.  Mypy's normal type
inference then correctly assigns ``str`` to the field variable.
"""

from __future__ import annotations

from typing import Callable

from mypy.nodes import NameExpr
from mypy.plugin import FunctionContext, Plugin
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
# Plugin class
# ---------------------------------------------------------------------------
class ProteanPlugin(Plugin):
    """Mypy plugin that resolves Protean field factory return types."""

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
