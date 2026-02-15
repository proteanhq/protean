"""Tests for FieldSpec in fields/spec.py.

Covers uncovered lines:
- Lines 24->26, 29, 32: _UNSET_TYPE repr and bool
- Line 201: Mutable default (list/dict) wrapping
- Line 229: error_messages in json_schema_extra
- Lines 327, 329, 331: __repr__ for Date, DateTime, FieldSpec fallback
- Lines 401-402, 409-414: resolve_fieldspecs duplicate warning
- Lines 449-450: _sanitize_string when bleach is available
"""

import datetime
import warnings


from protean.fields.spec import (
    FieldSpec,
    _UNSET,
    _UNSET_TYPE,
    _sanitize_string,
    resolve_fieldspecs,
)


# ---------------------------------------------------------------------------
# Tests: _UNSET sentinel
# ---------------------------------------------------------------------------
class TestUnsetSentinel:
    def test_repr(self):
        """Line 29: _UNSET_TYPE.__repr__."""
        assert repr(_UNSET) == "UNSET"

    def test_bool_is_false(self):
        """Line 32: _UNSET_TYPE.__bool__."""
        assert bool(_UNSET) is False

    def test_singleton(self):
        """Lines 24->26: _UNSET_TYPE is a singleton."""
        a = _UNSET_TYPE()
        b = _UNSET_TYPE()
        assert a is b


# ---------------------------------------------------------------------------
# Tests: FieldSpec resolve_field_kwargs
# ---------------------------------------------------------------------------
class TestFieldSpecResolveFieldKwargs:
    def test_mutable_list_default(self):
        """Line 201: Mutable list default wrapped in default_factory."""
        spec = FieldSpec(list, default=[1, 2, 3])
        kwargs = spec.resolve_field_kwargs()
        assert "default_factory" in kwargs
        # Calling the factory should return a copy of the list
        result = kwargs["default_factory"]()
        assert result == [1, 2, 3]
        assert result != [1, 2, 3]

    def test_mutable_dict_default(self):
        """Line 201: Mutable dict default wrapped in default_factory."""
        spec = FieldSpec(dict, default={"key": "val"})
        kwargs = spec.resolve_field_kwargs()
        assert "default_factory" in kwargs
        result = kwargs["default_factory"]()
        assert result == {"key": "val"}

    def test_error_messages_in_json_extra(self):
        """Line 229: error_messages added to json_schema_extra."""
        spec = FieldSpec(str, error_messages={"invalid": "Bad value"})
        kwargs = spec.resolve_field_kwargs()
        assert kwargs["json_schema_extra"]["_error_messages"] == {
            "invalid": "Bad value"
        }

    def test_callable_default(self):
        """Line 198: Callable default becomes default_factory."""

        def factory():
            return "generated"

        spec = FieldSpec(str, default=factory)
        kwargs = spec.resolve_field_kwargs()
        assert kwargs["default_factory"] is factory

    def test_description_included(self):
        spec = FieldSpec(str, description="A test field")
        kwargs = spec.resolve_field_kwargs()
        assert kwargs["description"] == "A test field"


# ---------------------------------------------------------------------------
# Tests: FieldSpec __repr__
# ---------------------------------------------------------------------------
class TestFieldSpecRepr:
    def test_repr_string(self):
        spec = FieldSpec(str)
        assert repr(spec).startswith("String(")

    def test_repr_text(self):
        spec = FieldSpec(str, field_kind="text")
        assert repr(spec).startswith("Text(")

    def test_repr_integer(self):
        spec = FieldSpec(int)
        assert repr(spec).startswith("Integer(")

    def test_repr_float(self):
        spec = FieldSpec(float)
        assert repr(spec).startswith("Float(")

    def test_repr_boolean(self):
        spec = FieldSpec(bool)
        assert repr(spec).startswith("Boolean(")

    def test_repr_identifier(self):
        spec = FieldSpec(str, field_kind="identifier")
        assert repr(spec).startswith("Identifier(")

    def test_repr_auto(self):
        spec = FieldSpec(str, field_kind="auto")
        assert repr(spec).startswith("Auto(")

    def test_repr_date(self):
        """Line 331: Date repr."""
        spec = FieldSpec(datetime.date)
        assert repr(spec).startswith("Date(")

    def test_repr_datetime(self):
        """Line 329: DateTime repr."""
        spec = FieldSpec(datetime.datetime)
        assert repr(spec).startswith("DateTime(")

    def test_repr_unknown_type_falls_back_to_fieldspec(self):
        """Line 335: FieldSpec fallback when type not in _FACTORY_NAMES."""
        spec = FieldSpec(bytes)
        assert repr(spec).startswith("FieldSpec(")

    def test_repr_list_type(self):
        """Line 327: List repr."""
        spec = FieldSpec(list[str])
        assert repr(spec).startswith("List(")

    def test_repr_dict_type(self):
        """Line 329: Dict repr."""
        spec = FieldSpec(dict)
        assert repr(spec).startswith("Dict(")

    def test_repr_with_max_length(self):
        spec = FieldSpec(str, max_length=50)
        r = repr(spec)
        assert "max_length=50" in r

    def test_repr_with_required(self):
        spec = FieldSpec(str, required=True)
        r = repr(spec)
        assert "required=True" in r

    def test_repr_with_identifier(self):
        spec = FieldSpec(str, identifier=True)
        r = repr(spec)
        assert "identifier=True" in r
        # identifier=True should not also show required
        assert "required" not in r

    def test_repr_with_default_string(self):
        spec = FieldSpec(str, default="hello")
        r = repr(spec)
        assert "default='hello'" in r

    def test_repr_with_default_number(self):
        spec = FieldSpec(int, default=42)
        r = repr(spec)
        assert "default=42" in r

    def test_repr_with_default_callable(self):
        def my_factory():
            return "val"

        spec = FieldSpec(str, default=my_factory)
        r = repr(spec)
        assert "default=my_factory" in r

    def test_repr_with_referenced_as(self):
        spec = FieldSpec(str, referenced_as="other_name")
        r = repr(spec)
        assert "referenced_as='other_name'" in r

    def test_repr_with_min_length(self):
        spec = FieldSpec(str, min_length=5)
        r = repr(spec)
        assert "min_length=5" in r

    def test_repr_with_min_max_value(self):
        spec = FieldSpec(int, min_value=1, max_value=100)
        r = repr(spec)
        assert "min_value=1" in r
        assert "max_value=100" in r

    def test_repr_string_sanitize_false(self):
        """Line 362-363: sanitize=False shown for String/Text types."""
        spec = FieldSpec(str)
        r = repr(spec)
        assert "sanitize=False" in r


# ---------------------------------------------------------------------------
# Tests: resolve_fieldspecs
# ---------------------------------------------------------------------------
class TestResolveFieldspecs:
    def test_duplicate_field_warning(self):
        """Lines 401-402, 409-414: Warning when field in both assignment and annotation."""
        # Create a class with a field in both assignment and annotation
        spec = FieldSpec(str, max_length=50)
        ns = {"name": spec, "__annotations__": {"name": spec}}
        cls = type("TestCls", (), ns)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            resolve_fieldspecs(cls)
            # Should warn about duplicate
            assert len(w) == 1
            assert "assignment and annotation" in str(w[0].message)


# ---------------------------------------------------------------------------
# Tests: _sanitize_string
# ---------------------------------------------------------------------------
class TestSanitizeString:
    def test_sanitize_removes_tags(self):
        """Lines 449-450: bleach.clean() is called if available."""
        try:
            import bleach  # noqa: F401

            result = _sanitize_string("<script>alert('xss')</script>hello")
            assert "<script>" not in result
            assert "hello" in result
        except ImportError:
            # bleach not installed, function returns value as-is
            result = _sanitize_string("<script>alert('xss')</script>hello")
            assert result == "<script>alert('xss')</script>hello"

    def test_sanitize_non_string_returns_as_is(self):
        """Line 443-444: Non-string value returned as-is."""
        assert _sanitize_string(42) == 42  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests: FieldSpec required + default warning
# ---------------------------------------------------------------------------
class TestFieldSpecWarning:
    def test_required_with_default_warns(self):
        """Lines 97-102: Warning when required=True with explicit default."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            FieldSpec(str, required=True, default="hello")
            assert len(w) == 1
            assert "required=True" in str(w[0].message)
