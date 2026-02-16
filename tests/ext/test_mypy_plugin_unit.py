"""Unit tests for mypy plugin functions in ext/mypy_plugin.py.

Tests the plugin helper functions directly to cover edge cases
that are hard to trigger through full mypy runs.

Covers:
- Re-export path in get_function_hook
- Type not available fallback in _field_factory_hook
- _get_kwarg_bool returning False for explicit False
- _extract_decorator_name for all 15 decorators and prefix patterns
- _extract_decorator_name_from_expr for AST node matching
- DECORATOR_BASE_CLASS_MAP completeness and correctness
- get_class_decorator_hook and get_customize_class_mro_hook
"""

from unittest.mock import MagicMock

from protean.ext.mypy_plugin import (
    DECORATOR_BASE_CLASS_MAP,
    FIELD_TYPE_MAP,
    ProteanPlugin,
    _REEXPORT_MAP,
    _extract_decorator_name,
    _extract_decorator_name_from_expr,
    _field_factory_hook,
    _get_kwarg_bool,
    _has_kwarg,
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


class TestExtractDecoratorName:
    """Tests for _extract_decorator_name (fullname-based matching)."""

    def test_all_15_decorators_canonical_prefix(self):
        """All 15 decorators are recognized with the canonical prefix."""
        for name in DECORATOR_BASE_CLASS_MAP:
            fullname = f"protean.domain.Domain.{name}"
            assert _extract_decorator_name(fullname) == name

    def test_all_15_decorators_init_prefix(self):
        """All 15 decorators are recognized with the __init__ prefix."""
        for name in DECORATOR_BASE_CLASS_MAP:
            fullname = f"protean.domain.__init__.Domain.{name}"
            assert _extract_decorator_name(fullname) == name

    def test_unknown_method_returns_none(self):
        """Unknown method name returns None."""
        assert _extract_decorator_name("protean.domain.Domain.unknown_method") is None

    def test_unknown_prefix_returns_none(self):
        """Unrecognized prefix returns None even with valid method name."""
        assert _extract_decorator_name("other.module.Domain.aggregate") is None

    def test_empty_string_returns_none(self):
        assert _extract_decorator_name("") is None

    def test_partial_prefix_returns_none(self):
        assert _extract_decorator_name("protean.domain.Domain") is None


class TestExtractDecoratorNameFromExpr:
    """Tests for _extract_decorator_name_from_expr (AST-based matching)."""

    def test_member_expr_known_decorator(self):
        """MemberExpr with a known decorator name is recognized."""
        from mypy.nodes import MemberExpr, NameExpr

        receiver = NameExpr("domain")
        expr = MemberExpr(receiver, "aggregate")
        assert _extract_decorator_name_from_expr(expr) == "aggregate"

    def test_call_expr_wrapping_member_expr(self):
        """CallExpr(@domain.aggregate()) is unwrapped to the MemberExpr."""
        from mypy.nodes import CallExpr, MemberExpr, NameExpr

        receiver = NameExpr("domain")
        member = MemberExpr(receiver, "aggregate")
        call = CallExpr(member, [], [], [])
        assert _extract_decorator_name_from_expr(call) == "aggregate"

    def test_unknown_method_name_returns_none(self):
        """MemberExpr with unknown method name returns None."""
        from mypy.nodes import MemberExpr, NameExpr

        receiver = NameExpr("domain")
        expr = MemberExpr(receiver, "not_a_decorator")
        assert _extract_decorator_name_from_expr(expr) is None

    def test_name_expr_returns_none(self):
        """A plain NameExpr (not MemberExpr) returns None."""
        from mypy.nodes import NameExpr

        expr = NameExpr("aggregate")
        assert _extract_decorator_name_from_expr(expr) is None

    def test_all_15_decorators_via_member_expr(self):
        """All 15 decorator names are recognized as MemberExpr."""
        from mypy.nodes import MemberExpr, NameExpr

        for name in DECORATOR_BASE_CLASS_MAP:
            receiver = NameExpr("domain")
            expr = MemberExpr(receiver, name)
            assert _extract_decorator_name_from_expr(expr) == name


class TestDecoratorBaseClassMap:
    """Tests for DECORATOR_BASE_CLASS_MAP completeness and correctness."""

    def test_has_15_entries(self):
        assert len(DECORATOR_BASE_CLASS_MAP) == 15

    def test_all_expected_decorators_present(self):
        expected = {
            "aggregate",
            "entity",
            "value_object",
            "command",
            "event",
            "domain_service",
            "command_handler",
            "event_handler",
            "application_service",
            "subscriber",
            "projection",
            "projector",
            "repository",
            "database_model",
            "email",
        }
        assert set(DECORATOR_BASE_CLASS_MAP.keys()) == expected

    def test_base_class_fqns_follow_naming_convention(self):
        """Each FQN should be protean.core.<module>.Base<ClassName>."""
        for decorator_name, fqn in DECORATOR_BASE_CLASS_MAP.items():
            assert fqn.startswith("protean.core."), (
                f"{fqn} doesn't start with protean.core."
            )
            assert ".Base" in fqn, f"{fqn} doesn't contain '.Base'"

    def test_aggregate_maps_correctly(self):
        assert (
            DECORATOR_BASE_CLASS_MAP["aggregate"]
            == "protean.core.aggregate.BaseAggregate"
        )

    def test_entity_maps_correctly(self):
        assert DECORATOR_BASE_CLASS_MAP["entity"] == "protean.core.entity.BaseEntity"


class TestGetClassDecoratorHook:
    """Tests for ProteanPlugin.get_class_decorator_hook."""

    def _make_plugin(self):
        from mypy.options import Options

        options = Options()
        return ProteanPlugin(options)

    def test_known_decorator_returns_hook(self):
        """A known Domain decorator fullname returns a hook callback."""
        plugin = self._make_plugin()
        hook = plugin.get_class_decorator_hook("protean.domain.Domain.aggregate")
        assert hook is not None
        assert callable(hook)

    def test_all_15_decorators_return_hooks(self):
        """All 15 decorators return hooks via canonical prefix."""
        plugin = self._make_plugin()
        for name in DECORATOR_BASE_CLASS_MAP:
            hook = plugin.get_class_decorator_hook(f"protean.domain.Domain.{name}")
            assert hook is not None, f"No hook returned for {name}"

    def test_unknown_fullname_returns_none(self):
        """Unknown fullname returns None."""
        plugin = self._make_plugin()
        hook = plugin.get_class_decorator_hook("unknown.module.SomeClass")
        assert hook is None

    def test_get_customize_class_mro_hook_returns_callback(self):
        """get_customize_class_mro_hook always returns the MRO callback."""
        plugin = self._make_plugin()
        hook = plugin.get_customize_class_mro_hook("any.class.Name")
        assert hook is not None
        assert callable(hook)
