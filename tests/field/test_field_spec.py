"""Tests for FieldSpec in fields/spec.py."""

import datetime
import warnings
from enum import Enum

import pytest

from protean._deprecation import (
    ProteanDeprecationWarning,
    RemovedInProtean10Warning,
)
from protean.core.aggregate import BaseAggregate
from protean.exceptions import ValidationError
from protean.fields import List, String, ValueObject
from protean.fields.spec import (
    FieldSpec,
    _UNSET,
    _UNSET_TYPE,
    _coerce_to_str,
    _sanitize_string,
    resolve_fieldspecs,
)


# ---------------------------------------------------------------------------
# Tests: _UNSET sentinel
# ---------------------------------------------------------------------------
class TestUnsetSentinel:
    def test_repr(self):
        assert repr(_UNSET) == "UNSET"

    def test_bool_is_false(self):
        assert bool(_UNSET) is False

    def test_singleton(self):
        a = _UNSET_TYPE()
        b = _UNSET_TYPE()
        assert a is b


# ---------------------------------------------------------------------------
# Tests: _coerce_to_str helper
# ---------------------------------------------------------------------------
class TestCoerceToStr:
    def test_coerce_none_passes_through(self):
        assert _coerce_to_str(None) is None

    def test_coerce_int_to_str(self):
        assert _coerce_to_str(42) == "42"


# ---------------------------------------------------------------------------
# Tests: FieldSpec resolve_type
# ---------------------------------------------------------------------------
class TestFieldSpecResolveType:
    def test_resolve_type_with_enum_choices(self):
        """Enum choices are resolved to Literal."""

        class Color(Enum):
            RED = "red"
            GREEN = "green"

        spec = FieldSpec(str, choices=Color)
        resolved = spec.resolve_type()
        assert "red" in str(resolved) or "Literal" in str(resolved)

    def test_resolve_type_with_list_choices(self):
        """List choices are resolved to Literal."""
        spec = FieldSpec(str, choices=["a", "b", "c"])
        resolved = spec.resolve_type()
        assert "Literal" in str(resolved)


# ---------------------------------------------------------------------------
# Tests: FieldSpec resolve_field_kwargs
# ---------------------------------------------------------------------------
class TestFieldSpecResolveFieldKwargs:
    def test_mutable_list_default(self):
        """Mutable list default is wrapped in default_factory."""
        spec = FieldSpec(list, default=[1, 2, 3])
        kwargs = spec.resolve_field_kwargs()
        assert "default_factory" in kwargs
        result = kwargs["default_factory"]()
        assert result == [1, 2, 3]
        assert result is not spec.default

    def test_mutable_dict_default(self):
        """Mutable dict default is wrapped in default_factory."""
        spec = FieldSpec(dict, default={"key": "val"})
        kwargs = spec.resolve_field_kwargs()
        assert "default_factory" in kwargs
        result = kwargs["default_factory"]()
        assert result == {"key": "val"}

    def test_error_messages_in_json_extra(self):
        """error_messages are stored in json_schema_extra."""
        spec = FieldSpec(str, error_messages={"invalid": "Bad value"})
        kwargs = spec.resolve_field_kwargs()
        assert kwargs["json_schema_extra"]["_error_messages"] == {
            "invalid": "Bad value"
        }

    def test_callable_default(self):
        """Callable default becomes default_factory."""

        def factory():
            return "generated"

        spec = FieldSpec(str, default=factory)
        kwargs = spec.resolve_field_kwargs()
        assert kwargs["default_factory"] is factory

    def test_description_included(self):
        spec = FieldSpec(str, description="A test field")
        kwargs = spec.resolve_field_kwargs()
        assert kwargs["description"] == "A test field"

    def test_non_str_type_skips_string_constraints(self):
        """Non-string types ignore max_length/min_length constraints."""
        spec = FieldSpec(int, max_length=10)
        kwargs = spec.resolve_field_kwargs()
        assert "max_length" not in kwargs


# ---------------------------------------------------------------------------
# Tests: FieldSpec resolve_annotated with validators
# ---------------------------------------------------------------------------
class TestFieldSpecWithValidators:
    def test_resolve_annotated_with_validators(self):
        """Validators are wrapped in AfterValidator."""

        def my_validator(v):
            if v == "bad":
                raise ValidationError({"field": ["Bad value"]})

        spec = FieldSpec(str, validators=[my_validator])
        annotated = spec.resolve_annotated()
        assert "Annotated" in str(annotated)

    def test_validator_raises_validation_error(self, test_domain):
        """Validator that raises ProteanValidationError is converted to ValueError for Pydantic."""

        def no_spaces(v):
            if " " in v:
                raise ValidationError({"field": ["No spaces allowed"]})

        class Validated(BaseAggregate):
            code: String(max_length=50, validators=[no_spaces])

        test_domain.register(Validated)
        test_domain.init(traverse=False)

        with pytest.raises(ValidationError):
            Validated(code="has spaces")


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
        spec = FieldSpec(datetime.date)
        assert repr(spec).startswith("Date(")

    def test_repr_datetime(self):
        spec = FieldSpec(datetime.datetime)
        assert repr(spec).startswith("DateTime(")

    def test_repr_unknown_type_falls_back_to_fieldspec(self):
        spec = FieldSpec(bytes)
        assert repr(spec).startswith("FieldSpec(")

    def test_repr_list_type(self):
        spec = FieldSpec(list[str])
        assert repr(spec).startswith("List(")

    def test_repr_dict_type(self):
        spec = FieldSpec(dict)
        assert repr(spec).startswith("Dict(")

    def test_repr_with_max_length(self):
        spec = FieldSpec(str, max_length=50)
        assert "max_length=50" in repr(spec)

    def test_repr_with_required(self):
        spec = FieldSpec(str, required=True)
        assert "required=True" in repr(spec)

    def test_repr_with_identifier(self):
        spec = FieldSpec(str, identifier=True)
        r = repr(spec)
        assert "identifier=True" in r
        # identifier=True should not also show required
        assert "required" not in r

    def test_repr_with_default_string(self):
        spec = FieldSpec(str, default="hello")
        assert "default='hello'" in repr(spec)

    def test_repr_with_default_number(self):
        spec = FieldSpec(int, default=42)
        assert "default=42" in repr(spec)

    def test_repr_with_default_callable(self):
        def my_factory():
            return "val"

        spec = FieldSpec(str, default=my_factory)
        assert "default=my_factory" in repr(spec)

    def test_repr_with_referenced_as(self):
        spec = FieldSpec(str, referenced_as="other_name")
        assert "referenced_as='other_name'" in repr(spec)

    def test_repr_with_min_length(self):
        spec = FieldSpec(str, min_length=5)
        assert "min_length=5" in repr(spec)

    def test_repr_with_min_max_value(self):
        spec = FieldSpec(int, min_value=1, max_value=100)
        r = repr(spec)
        assert "min_value=1" in r
        assert "max_value=100" in r

    def test_repr_string_sanitize_false(self):
        """sanitize=False is shown for String/Text types."""
        spec = FieldSpec(str)
        assert "sanitize=False" in repr(spec)


# ---------------------------------------------------------------------------
# Tests: resolve_fieldspecs
# ---------------------------------------------------------------------------
class TestResolveFieldspecs:
    def test_duplicate_field_warning(self):
        """Warning when field declared in both assignment and annotation."""
        spec = FieldSpec(str, max_length=50)
        ns = {"name": spec, "__annotations__": {"name": spec}}
        cls = type("TestCls", (), ns)

        with pytest.warns(
            UserWarning,
            match=r"Field 'name' declared in both assignment and annotation",
        ):
            resolve_fieldspecs(cls)


# ---------------------------------------------------------------------------
# Tests: _sanitize_string
# ---------------------------------------------------------------------------
class TestSanitizeString:
    def test_sanitize_removes_tags(self):
        """bleach.clean() is called if available."""
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
        assert _sanitize_string(42) == 42  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tests: FieldSpec required + default warning
# ---------------------------------------------------------------------------
class TestFieldSpecWarning:
    def test_required_with_default_warns(self):
        with pytest.warns(
            UserWarning,
            match=r"required=True.*default.*effectively not required",
        ):
            FieldSpec(str, required=True, default="hello")

    def test_required_without_default_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            FieldSpec(str, required=True)
            assert len(w) == 0


# ---------------------------------------------------------------------------
# Tests: validate_default for identity fields
# ---------------------------------------------------------------------------
class TestFieldSpecValidateDefault:
    def test_identifier_field_has_validate_default(self):
        """FieldSpec for an identifier Auto field should include
        validate_default=True in resolved kwargs."""
        spec = FieldSpec(str, field_kind="auto", identifier=True)
        spec._increment = False
        spec._identity_strategy = None
        spec._identity_function = None
        spec._identity_type = None

        kwargs = spec.resolve_field_kwargs()
        assert kwargs.get("validate_default") is True

    def test_non_identifier_field_no_validate_default(self):
        """Non-identifier fields should NOT have validate_default."""
        spec = FieldSpec(str, field_kind="auto", identifier=False)
        spec._increment = False
        spec._identity_strategy = None
        spec._identity_function = None
        spec._identity_type = None

        kwargs = spec.resolve_field_kwargs()
        assert "validate_default" not in kwargs

    def test_increment_field_no_validate_default(self):
        """Auto-increment identifier fields should NOT have validate_default
        (they use default=None, not default_factory)."""
        spec = FieldSpec(int, field_kind="auto", identifier=True)
        spec._increment = True
        spec._identity_strategy = None
        spec._identity_function = None
        spec._identity_type = None

        kwargs = spec.resolve_field_kwargs()
        assert "validate_default" not in kwargs

    def test_identifier_field_with_explicit_default_no_validate_default(self):
        """When an explicit default is provided, validate_default should not
        be added (the default_factory path is not taken)."""
        spec = FieldSpec(str, field_kind="auto", identifier=True, default="fixed-id")
        spec._increment = False
        spec._identity_strategy = None
        spec._identity_function = None
        spec._identity_type = None

        kwargs = spec.resolve_field_kwargs()
        assert "validate_default" not in kwargs

    def test_identifier_spec_with_kind_identifier(self):
        """FieldSpec with field_kind='identifier' also gets validate_default."""
        spec = FieldSpec(str, field_kind="identifier", identifier=True)

        kwargs = spec.resolve_field_kwargs()
        assert kwargs.get("validate_default") is True


# ---------------------------------------------------------------------------
# Tests: deprecated ``pickled`` argument on List()
#
# ``pickled`` is a dead legacy kwarg — accepted but never forwarded to the
# FieldSpec. Passing it (with any value) is deprecated and removed at v1.0.0.
# ---------------------------------------------------------------------------
class TestListPickledDeprecation:
    def test_pickled_true_is_deprecated(self):
        with pytest.warns(
            RemovedInProtean10Warning,
            match=r"`pickled` argument on `List` is deprecated.*v1\.0\.0",
        ):
            spec = List(pickled=True)

        # The kwarg is ignored, not fatal — a usable list spec is returned...
        assert isinstance(spec, FieldSpec)
        # ...and, crucially, it is *never forwarded* to the FieldSpec: the
        # resulting spec is structurally identical to one built without it.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert vars(spec) == vars(List())
        assert not hasattr(spec, "pickled")

    def test_pickled_false_is_deprecated(self):
        """Even an explicit ``pickled=False`` warns — the arg is going away."""
        with pytest.warns(RemovedInProtean10Warning):
            List(pickled=False)

    @pytest.mark.parametrize("value", [None, 0, "", False, True])
    def test_pickled_warns_for_any_explicit_value(self, value):
        """The sentinel design means *any* explicit value warns, including
        falsy ones — a future ``if pickled:`` regression would silently stop
        warning on ``None``/``0``/``""``/``False`` and go uncaught otherwise."""
        with pytest.warns(RemovedInProtean10Warning):
            List(pickled=value)

    def test_pickled_warns_when_passed_positionally(self):
        """``pickled`` is the second positional parameter; a positional pass
        must warn just as a keyword pass does."""
        with pytest.warns(RemovedInProtean10Warning):
            List(String(), True)

    def test_list_without_pickled_does_not_warn(self):
        """The common paths emit no deprecation warning."""
        from protean.core.value_object import BaseValueObject

        class Addr(BaseValueObject):
            street: str | None = None

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            List(String())
            List(content_type=ValueObject(Addr))
            List()

        assert not [
            w for w in caught if issubclass(w.category, ProteanDeprecationWarning)
        ]
