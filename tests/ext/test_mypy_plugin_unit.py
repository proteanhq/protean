"""Unit tests for mypy plugin functions in ext/mypy_plugin.py.

Tests the plugin helper functions directly to cover edge cases
that are hard to trigger through full mypy runs.

Covers:
- Lines 108-114: Re-export path in get_function_hook
- Lines 135-137: Type not available fallback in _field_factory_hook
- Lines 173-175: _get_kwarg_bool returning False for explicit False
"""

from unittest.mock import MagicMock

from protean.ext.mypy_plugin import (
    FIELD_TYPE_MAP,
    ProteanPlugin,
    _REEXPORT_MAP,
    _get_kwarg_bool,
    _has_kwarg,
    _field_factory_hook,
)


class TestReexportMap:
    def test_reexport_map_built(self):
        """The re-export map should be populated for all canonical names."""
        assert len(_REEXPORT_MAP) > 0
        # protean.fields.simple.String → protean.fields.String
        assert "protean.fields.String" in _REEXPORT_MAP
        assert _REEXPORT_MAP["protean.fields.String"] == "protean.fields.simple.String"

    def test_all_canonical_names_have_reexport(self):
        for canonical in FIELD_TYPE_MAP:
            parts = canonical.split(".")
            if len(parts) >= 4:
                reexported = f"{parts[0]}.{parts[1]}.{parts[-1]}"
                assert reexported in _REEXPORT_MAP


class TestProteanPluginGetFunctionHook:
    def _make_plugin(self):
        from mypy.options import Options

        options = Options()
        return ProteanPlugin(options)

    def _make_ctx(self, type_name="builtins.str"):
        """Create a mock FunctionContext."""
        ctx = MagicMock()
        mock_type = MagicMock(name=type_name)
        ctx.api.named_generic_type.return_value = mock_type
        ctx.default_return_type = MagicMock(name="default_return")
        ctx.arg_names = []
        ctx.args = []
        return ctx, mock_type

    def test_canonical_name_returns_hook(self):
        """Lines 96-103: Canonical fullname returns a hook."""
        plugin = self._make_plugin()
        hook = plugin.get_function_hook("protean.fields.simple.String")
        assert hook is not None

    def test_canonical_hook_invocation_required(self):
        """Line 100-101: Calling hook from canonical path with required=True."""
        from mypy.nodes import NameExpr

        plugin = self._make_plugin()
        hook = plugin.get_function_hook("protean.fields.simple.String")
        ctx, mock_type = self._make_ctx()
        # Set required=True so we get the base type (no Optional wrapping)
        true_expr = NameExpr("True")
        true_expr.name = "True"
        ctx.arg_names = [["required"]]
        ctx.args = [[true_expr]]
        result = hook(ctx)
        assert result is mock_type

    def test_reexport_name_returns_hook(self):
        """Lines 108-114: Re-exported fullname returns a hook."""
        plugin = self._make_plugin()
        hook = plugin.get_function_hook("protean.fields.String")
        assert hook is not None

    def test_reexport_hook_invocation_required(self):
        """Lines 111-112: Calling hook from re-export path with required=True."""
        from mypy.nodes import NameExpr

        plugin = self._make_plugin()
        hook = plugin.get_function_hook("protean.fields.String")
        ctx, mock_type = self._make_ctx()
        true_expr = NameExpr("True")
        true_expr.name = "True"
        ctx.arg_names = [["required"]]
        ctx.args = [[true_expr]]
        result = hook(ctx)
        assert result is mock_type

    def test_unknown_name_returns_none(self):
        """Line 116: Unknown fullname returns None."""
        plugin = self._make_plugin()
        hook = plugin.get_function_hook("unknown.module.Unknown")
        assert hook is None


class TestFieldFactoryHook:
    def test_type_not_available_fallback(self):
        """Lines 135-137: KeyError/AssertionError falls back to default."""
        ctx = MagicMock()
        ctx.api.named_generic_type.side_effect = KeyError("not found")
        ctx.default_return_type = MagicMock(name="default_return")
        ctx.arg_names = []
        ctx.args = []

        result = _field_factory_hook(ctx, "builtins.str", False)
        assert result is ctx.default_return_type

    def test_assertion_error_fallback(self):
        """Lines 135-137: AssertionError also falls back."""
        ctx = MagicMock()
        ctx.api.named_generic_type.side_effect = AssertionError("assertion failed")
        ctx.default_return_type = MagicMock(name="default_return")
        ctx.arg_names = []
        ctx.args = []

        result = _field_factory_hook(ctx, "builtins.int", False)
        assert result is ctx.default_return_type


class TestGetKwargBool:
    def _make_ctx(self, arg_names, args):
        ctx = MagicMock()
        ctx.arg_names = arg_names
        ctx.args = args
        return ctx

    def test_true_value(self):
        """Line 172: NameExpr.name == 'True' returns True."""
        expr = MagicMock()
        expr.__class__.__name__ = "NameExpr"
        # Use actual NameExpr-like check
        from mypy.nodes import NameExpr

        name_expr = NameExpr("True")
        name_expr.name = "True"

        ctx = self._make_ctx([["required"]], [[name_expr]])
        result = _get_kwarg_bool(ctx, "required", default=False)
        assert result is True

    def test_false_value(self):
        """Lines 173-175: NameExpr.name == 'False' returns False."""
        from mypy.nodes import NameExpr

        name_expr = NameExpr("False")
        name_expr.name = "False"

        ctx = self._make_ctx([["required"]], [[name_expr]])
        result = _get_kwarg_bool(ctx, "required", default=True)
        assert result is False

    def test_non_name_expr_returns_default(self):
        """Line 175: Non-NameExpr returns default."""
        expr = MagicMock()  # Not a NameExpr
        ctx = self._make_ctx([["required"]], [[expr]])
        result = _get_kwarg_bool(ctx, "required", default=False)
        assert result is False

    def test_missing_arg_returns_default(self):
        """Line 176: Missing arg returns default."""
        ctx = self._make_ctx([["other"]], [[MagicMock()]])
        result = _get_kwarg_bool(ctx, "required", default=True)
        assert result is True


class TestHasKwarg:
    def test_present_kwarg(self):
        ctx = MagicMock()
        ctx.arg_names = [["default"]]
        assert _has_kwarg(ctx, "default") is True

    def test_missing_kwarg(self):
        ctx = MagicMock()
        ctx.arg_names = [["required"]]
        assert _has_kwarg(ctx, "default") is False
