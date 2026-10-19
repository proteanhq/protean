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

from mypy.nodes import SymbolTable

from protean.ext.mypy_plugin import (
    _REEXPORT_MAP,
    DECORATOR_BASE_CLASS_MAP,
    FIELD_TYPE_MAP,
    ProteanPlugin,
    _custom_field_hook,
    _extract_decorator_name,
    _extract_decorator_name_from_expr,
    _field_factory_hook,
    _get_kwarg_bool,
    _has_default,
    _resolve_custom_fullname,
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
        """Canonical fullname returns a hook."""
        plugin = self._make_plugin()
        hook = plugin.get_function_hook("protean.fields.simple.String")
        assert hook is not None

    def test_canonical_hook_invocation_required(self):
        """Calling hook from canonical path with required=True."""
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
        """Re-exported fullname returns a hook."""
        plugin = self._make_plugin()
        hook = plugin.get_function_hook("protean.fields.String")
        assert hook is not None

    def test_reexport_hook_invocation_required(self):
        """Calling hook from re-export path with required=True."""
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
        """Unknown fullname returns None."""
        plugin = self._make_plugin()
        hook = plugin.get_function_hook("unknown.module.Unknown")
        assert hook is None


class TestFieldFactoryHook:
    def test_type_not_available_fallback(self):
        """KeyError/AssertionError falls back to default."""
        ctx = MagicMock()
        ctx.api.named_generic_type.side_effect = KeyError("not found")
        ctx.default_return_type = MagicMock(name="default_return")
        ctx.arg_names = []
        ctx.args = []

        result = _field_factory_hook(ctx, "builtins.str", False)
        assert result is ctx.default_return_type

    def test_assertion_error_fallback(self):
        """AssertionError also falls back."""
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
        """NameExpr.name == 'True' returns True."""
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
        """NameExpr.name == 'False' returns False."""
        from mypy.nodes import NameExpr

        name_expr = NameExpr("False")
        name_expr.name = "False"

        ctx = self._make_ctx([["required"]], [[name_expr]])
        result = _get_kwarg_bool(ctx, "required", default=True)
        assert result is False

    def test_non_name_expr_returns_default(self):
        """Non-NameExpr returns default."""
        expr = MagicMock()  # Not a NameExpr
        ctx = self._make_ctx([["required"]], [[expr]])
        result = _get_kwarg_bool(ctx, "required", default=False)
        assert result is False

    def test_missing_arg_returns_default(self):
        """Missing arg returns default."""
        ctx = self._make_ctx([["other"]], [[MagicMock()]])
        result = _get_kwarg_bool(ctx, "required", default=True)
        assert result is True


class TestHasDefault:
    def _ctx(self, name: str, expr: object) -> MagicMock:
        ctx = MagicMock()
        ctx.arg_names = [[name]]
        ctx.args = [[expr]]
        return ctx

    def test_present_default(self):
        from mypy.nodes import StrExpr

        assert _has_default(self._ctx("default", StrExpr("x"))) is True

    def test_default_none_is_not_a_default(self):
        from mypy.nodes import NameExpr

        assert _has_default(self._ctx("default", NameExpr("None"))) is False

    def test_missing_default(self):
        from mypy.nodes import NameExpr

        assert _has_default(self._ctx("required", NameExpr("True"))) is False


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

    def test_has_19_entries(self):
        assert len(DECORATOR_BASE_CLASS_MAP) == 19

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
            "query",
            "query_handler",
            "upcaster",
            "process_manager",
            "repository",
            "database_model",
            "email",
        }
        assert set(DECORATOR_BASE_CLASS_MAP.keys()) == expected

    def test_base_class_fqns_follow_naming_convention(self):
        """Each FQN should be protean.core.<module>.Base<ClassName>."""
        for fqn in DECORATOR_BASE_CLASS_MAP.values():
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


class TestIsSubclass:
    """Tests for _is_subclass helper."""

    def test_is_subclass_when_present(self):
        from protean.ext.mypy_plugin import _is_subclass

        info = MagicMock()
        base_info = MagicMock()
        base_info.fullname = "protean.core.aggregate.BaseAggregate"
        mro_entry = MagicMock()
        mro_entry.fullname = "protean.core.aggregate.BaseAggregate"
        info.mro = [mro_entry]
        assert _is_subclass(info, base_info) is True

    def test_is_subclass_when_absent(self):
        from protean.ext.mypy_plugin import _is_subclass

        info = MagicMock()
        base_info = MagicMock()
        base_info.fullname = "protean.core.aggregate.BaseAggregate"
        mro_entry = MagicMock()
        mro_entry.fullname = "builtins.object"
        info.mro = [mro_entry]
        assert _is_subclass(info, base_info) is False

    def test_is_subclass_empty_mro(self):
        from protean.ext.mypy_plugin import _is_subclass

        info = MagicMock()
        base_info = MagicMock()
        base_info.fullname = "protean.core.aggregate.BaseAggregate"
        info.mro = []
        assert _is_subclass(info, base_info) is False


class TestMakeSymbolTableNode:
    """Tests for _make_symbol_table_node helper."""

    def test_creates_mdef_node(self):
        from mypy.nodes import MDEF, Var

        from protean.ext.mypy_plugin import _make_symbol_table_node

        var = Var("test_var")
        node = _make_symbol_table_node(var)
        assert node.kind == MDEF
        assert node.node is var


class TestMaybeInjectAutoId:
    """Tests for _maybe_inject_auto_id."""

    def test_skips_non_auto_id_decorators(self):
        from protean.ext.mypy_plugin import _maybe_inject_auto_id

        ctx = MagicMock()
        info = MagicMock()
        info.names = {}
        info.mro = [info]
        _maybe_inject_auto_id(ctx, info, "command")
        assert "id" not in info.names

    def test_skips_when_id_already_present(self):
        from protean.ext.mypy_plugin import _maybe_inject_auto_id

        ctx = MagicMock()
        info = MagicMock()
        info.names = {"id": MagicMock()}
        info.mro = [info]
        _maybe_inject_auto_id(ctx, info, "aggregate")
        # id should still be the original, not replaced
        ctx.api.named_type.assert_not_called()

    def test_injects_id_for_aggregate(self):
        from unittest.mock import patch

        from protean.ext.mypy_plugin import _maybe_inject_auto_id

        ctx = MagicMock()
        ctx.api.named_type.return_value = MagicMock()
        info = MagicMock()
        info.names = {}
        info.fullname = "test.MyAggregate"
        mro_entry = MagicMock()
        mro_entry.names = {}
        info.mro = [mro_entry]

        # Patch both Var and _make_symbol_table_node to avoid mypy internal validation
        mock_sym = MagicMock()
        with (
            patch("protean.ext.mypy_plugin.Var") as MockVar,
            patch(
                "protean.ext.mypy_plugin._make_symbol_table_node", return_value=mock_sym
            ),
        ):
            MockVar.return_value = MagicMock()
            _maybe_inject_auto_id(ctx, info, "aggregate")
            assert "id" in info.names
            MockVar.assert_called_once()

    def test_injects_id_for_entity(self):
        from unittest.mock import patch

        from protean.ext.mypy_plugin import _maybe_inject_auto_id

        ctx = MagicMock()
        ctx.api.named_type.return_value = MagicMock()
        info = MagicMock()
        info.names = {}
        info.fullname = "test.MyEntity"
        mro_entry = MagicMock()
        mro_entry.names = {}
        info.mro = [mro_entry]

        mock_sym = MagicMock()
        with (
            patch("protean.ext.mypy_plugin.Var") as MockVar,
            patch(
                "protean.ext.mypy_plugin._make_symbol_table_node", return_value=mock_sym
            ),
        ):
            MockVar.return_value = MagicMock()
            _maybe_inject_auto_id(ctx, info, "entity")
            assert "id" in info.names
            MockVar.assert_called_once()


class TestInjectBaseClass:
    """Tests for _inject_base_class."""

    def test_returns_when_base_sym_is_none(self):
        from protean.ext.mypy_plugin import _inject_base_class

        ctx = MagicMock()
        ctx.api.lookup_fully_qualified_or_none.return_value = None
        ctx.cls.info = MagicMock()
        _inject_base_class(ctx, "protean.core.aggregate.BaseAggregate", "aggregate")
        # Should return early without error

    def test_returns_when_base_sym_node_not_typeinfo(self):
        from protean.ext.mypy_plugin import _inject_base_class

        ctx = MagicMock()
        base_sym = MagicMock()
        base_sym.node = "not a TypeInfo"
        ctx.api.lookup_fully_qualified_or_none.return_value = base_sym
        ctx.cls.info = MagicMock()
        _inject_base_class(ctx, "protean.core.aggregate.BaseAggregate", "aggregate")
        # Should return early without error


class TestCustomizeClassMroCallback:
    """Tests for _customize_class_mro_callback."""

    def test_no_decorators_does_nothing(self):
        from protean.ext.mypy_plugin import _customize_class_mro_callback

        ctx = MagicMock()
        ctx.cls.decorators = []
        _customize_class_mro_callback(ctx)
        # Should return without error

    def test_non_matching_decorator_does_nothing(self):
        from mypy.nodes import NameExpr

        from protean.ext.mypy_plugin import _customize_class_mro_callback

        ctx = MagicMock()
        # A plain NameExpr is not a MemberExpr, so it won't match
        ctx.cls.decorators = [NameExpr("some_decorator")]
        _customize_class_mro_callback(ctx)
        ctx.api.lookup_fully_qualified_or_none.assert_not_called()


class TestCustomFieldHook:
    """The Custom factory's hook, driven directly."""

    def test_reexported_name_resolves_to_canonical(self):
        assert (
            _resolve_custom_fullname("protean.fields.Custom")
            == "protean.fields.simple.Custom"
        )

    def test_unrelated_name_does_not_resolve(self):
        assert _resolve_custom_fullname("protean.fields.simple.String") is None

    def test_missing_first_argument_falls_back(self):
        """Custom() with no positional argument keeps the default return type."""
        ctx = MagicMock()
        ctx.args = []
        ctx.arg_types = []
        ctx.default_return_type = MagicMock(name="default_return")

        assert _custom_field_hook(ctx) is ctx.default_return_type

    def test_unresolvable_first_argument_falls_back(self):
        """A first argument mypy cannot resolve keeps the default return type."""
        from mypy.types import AnyType, TypeOfAny

        ctx = MagicMock()
        ctx.args = [[MagicMock()]]
        ctx.arg_types = [[AnyType(TypeOfAny.special_form)]]
        ctx.default_return_type = MagicMock(name="default_return")

        assert _custom_field_hook(ctx) is ctx.default_return_type

    def test_type_type_argument_is_unwrapped(self):
        """``Custom(Color)`` passed as type[Color] resolves to ``Color | None``."""
        from mypy.nodes import Block, ClassDef, TypeInfo
        from mypy.types import Instance, NoneType, TypeType, UnionType

        class_def = ClassDef("Color", Block([]))
        class_def.fullname = "somewhere.Color"
        info = TypeInfo(SymbolTable(), class_def, "somewhere")
        color = Instance(info, [])

        ctx = MagicMock()
        ctx.args = [[MagicMock()]]
        ctx.arg_types = [[TypeType(color)]]
        ctx.arg_names = []

        result = _custom_field_hook(ctx)
        # Optional by default: Custom(Color) is Color | None
        assert isinstance(result, UnionType)
        assert color in result.items
        assert any(isinstance(item, NoneType) for item in result.items)


def _class_body_statements(source: str) -> dict[str, object]:
    """Parse ``source`` with mypy's parser and key the class body by first name."""
    from mypy.errors import Errors
    from mypy.nodes import AssignmentStmt, ClassDef, NameExpr
    from mypy.options import Options
    from mypy.parse import parse

    options = Options()
    tree = parse(source, "fixture.py", "fixture", Errors(options), options, eager=True)
    class_def = tree.defs[0]
    assert isinstance(class_def, ClassDef)
    statements: dict[str, object] = {}
    for stmt in class_def.defs.body:
        assert isinstance(stmt, AssignmentStmt)
        first = stmt.lvalues[0]
        key = first.name if isinstance(first, NameExpr) else "tuple"
        statements[key] = stmt
    return statements


class TestIsRejectedFieldAnnotation:
    """Which class-body annotations count as annotation-only field declarations."""

    _SOURCE = """
class Order:
    with_kwargs: String(required=True, max_length=50)
    no_kwargs: String()
    association: HasMany(LineItem)
    plain_type: int
    string_annotation: "int"
    bare_field_name: String
    typed_annotation: str = String(required=True)
    arithmetic: 1 + 2
    builtin_call: str()
    first, second = 1, 2
"""

    def _check(self, name: str) -> bool:
        from protean.ext.mypy_plugin import _is_rejected_field_annotation

        return _is_rejected_field_annotation(_class_body_statements(self._SOURCE)[name])

    def test_field_call_with_keywords_is_rejected_field(self):
        assert self._check("with_kwargs") is True

    def test_field_call_without_keywords_is_rejected_field(self):
        assert self._check("no_kwargs") is True

    def test_association_call_is_rejected_field(self):
        assert self._check("association") is True

    def test_plain_type_annotation_is_left_alone(self):
        assert self._check("plain_type") is False

    def test_string_annotation_is_left_alone(self):
        assert self._check("string_annotation") is False

    def test_bare_field_name_is_left_alone(self):
        """``name: String`` is handled by the type-analyze hook instead."""
        assert self._check("bare_field_name") is False

    def test_typed_annotation_is_left_alone(self):
        assert self._check("typed_annotation") is False

    def test_invalid_expression_without_a_call_is_left_alone(self):
        assert self._check("arithmetic") is False

    def test_call_to_a_non_field_without_keywords_is_left_alone(self):
        assert self._check("builtin_call") is False

    def test_tuple_target_is_left_alone(self):
        assert self._check("tuple") is False

    def test_non_assignment_is_not_a_field(self):
        from protean.ext.mypy_plugin import _is_rejected_field_annotation

        assert _is_rejected_field_annotation(object()) is False


class TestIsClassVar:
    """Which unanalyzed annotations count as ``ClassVar``."""

    def _check(self, annotation: object, node_fullname: str | None = "", found=True):
        from protean.ext.mypy_plugin import _is_class_var

        ctx = MagicMock()
        if not found:
            ctx.api.lookup_qualified.return_value = None
        elif node_fullname is None:
            ctx.api.lookup_qualified.return_value.node = None
        else:
            ctx.api.lookup_qualified.return_value.node.fullname = node_fullname
        return _is_class_var(ctx, annotation)

    def test_aliased_typing_class_var_counts(self):
        from mypy.types import UnboundType

        assert self._check(UnboundType("CV"), "typing.ClassVar") is True

    def test_typing_extensions_class_var_counts(self):
        from mypy.types import UnboundType

        assert self._check(UnboundType("ClassVar"), "typing_extensions.ClassVar")

    def test_other_name_does_not_count(self):
        from mypy.types import UnboundType

        assert self._check(UnboundType("str"), "builtins.str") is False

    def test_unresolved_name_does_not_count(self):
        from mypy.types import UnboundType

        assert self._check(UnboundType("Missing"), found=False) is False

    def test_name_without_a_node_does_not_count(self):
        from mypy.types import UnboundType

        assert self._check(UnboundType("Pending"), node_fullname=None) is False

    def test_union_annotation_does_not_count(self):
        from mypy.types import UnboundType, UnionType

        union = UnionType([UnboundType("str"), UnboundType("None")])
        assert self._check(union, "typing.ClassVar") is False


class TestParentInit:
    """Which parent ``__init__`` a class inherits, and what its keywords are."""

    def _entry(
        self, fullname: str, init: object = None, synthesized: bool = False
    ) -> MagicMock:
        from mypy.nodes import MDEF, SymbolTableNode

        entry = MagicMock()
        entry.fullname = fullname
        entry.names = {} if init is None else {"__init__": SymbolTableNode(MDEF, init)}
        entry.metadata = {"protean": {"synthesized_init": True}} if synthesized else {}
        return entry

    def _init(self, kinds: list, names: list[str], typed: bool = True) -> object:
        from mypy.nodes import Block, ClassDef, FuncDef, SymbolTable, TypeInfo
        from mypy.types import AnyType, CallableType, Instance, TypeOfAny

        func = FuncDef("__init__", [], Block([]))
        if typed:
            any_type = AnyType(TypeOfAny.special_form)
            function_info = TypeInfo(
                SymbolTable(), ClassDef("function", Block([])), "builtins"
            )
            func.type = CallableType(
                [any_type] * len(kinds),
                kinds,
                names,
                any_type,
                Instance(function_info, []),
            )
        return func

    def _nearest(self, *entries: MagicMock) -> MagicMock | None:
        from protean.ext.mypy_plugin import _nearest_parent_init

        info = MagicMock()
        info.mro = [MagicMock(), *entries]
        found = _nearest_parent_init(info)
        return None if found is None else found[0]

    def _keywords(self, init: object) -> list[str]:
        from mypy.nodes import MDEF, SymbolTableNode

        from protean.ext.mypy_plugin import _init_keywords

        return [name for name, _ in _init_keywords(SymbolTableNode(MDEF, init))]

    def test_parent_without_its_own_init_is_skipped(self):
        from mypy.nodes import ARG_NAMED_OPT, ARG_POS

        mixin = self._entry("app.Mixin")
        parent = self._entry(
            "app.Auditable",
            self._init([ARG_POS, ARG_NAMED_OPT], ["self", "changed_by"]),
            synthesized=True,
        )
        assert self._nearest(mixin, parent) is parent

    def test_nearest_parent_wins(self):
        from mypy.nodes import ARG_NAMED_OPT, ARG_POS

        handmade = self._entry(
            "app.Handmade", self._init([ARG_POS, ARG_NAMED_OPT], ["self", "left"])
        )
        grandparent = self._entry(
            "app.Tracked",
            self._init([ARG_POS, ARG_NAMED_OPT], ["self", "changed_at"]),
            synthesized=True,
        )
        assert self._nearest(handmade, grandparent) is handmade

    def test_walk_stops_at_framework_classes(self):
        from mypy.nodes import ARG_NAMED_OPT, ARG_POS

        base = self._entry(
            "protean.core.aggregate.BaseAggregate",
            self._init([ARG_POS, ARG_NAMED_OPT], ["self", "internal"]),
        )
        assert self._nearest(base) is None

    def test_no_parent_init_below_an_unmarked_mro(self):
        assert self._nearest(self._entry("app.Mixin")) is None

    def _generated(self, *entries: MagicMock) -> list[str]:
        from protean.ext.mypy_plugin import _generated_init_keywords

        info = MagicMock()
        info.mro = [MagicMock(), *entries]
        return [name for name, _ in _generated_init_keywords(info)]

    def test_generated_keywords_come_from_every_generated_parent(self):
        from mypy.nodes import ARG_NAMED_OPT, ARG_POS, MDEF, SymbolTableNode

        left = self._entry(
            "app.Left",
            self._init([ARG_POS, ARG_NAMED_OPT], ["self", "left"]),
            synthesized=True,
        )
        right = self._entry("app.Right")
        right.names = {
            "__init__": SymbolTableNode(
                MDEF,
                self._init(
                    [ARG_POS, ARG_NAMED_OPT, ARG_NAMED_OPT], ["self", "right", "left"]
                ),
                plugin_generated=True,
            )
        }
        assert self._generated(left, right) == ["left", "right"]

    def test_generated_keywords_skip_hand_written_and_missing_inits(self):
        from mypy.nodes import ARG_NAMED_OPT, ARG_POS

        mixin = self._entry("app.Mixin")
        handmade = self._entry(
            "app.Handmade", self._init([ARG_POS, ARG_NAMED_OPT], ["self", "left"])
        )
        base = self._entry(
            "protean.core.aggregate.BaseAggregate",
            self._init([ARG_POS, ARG_NAMED_OPT], ["self", "internal"]),
            synthesized=True,
        )
        assert self._generated(mixin, handmade, base) == []

    def test_keywords_follow_the_signature(self):
        from mypy.nodes import ARG_NAMED_OPT, ARG_POS

        init = self._init(
            [ARG_POS, ARG_NAMED_OPT, ARG_NAMED_OPT],
            ["self", "changed_by", "changed_at"],
        )
        assert self._keywords(init) == ["changed_by", "changed_at"]

    def test_fieldless_init_has_no_keywords(self):
        from mypy.nodes import ARG_POS

        assert self._keywords(self._init([ARG_POS], ["self"])) == []

    def test_untyped_init_has_no_keywords(self):
        from mypy.nodes import ARG_POS

        assert self._keywords(self._init([ARG_POS], ["self"], typed=False)) == []
