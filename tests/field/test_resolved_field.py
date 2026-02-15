"""Tests for ResolvedField in fields/resolved.py."""

import datetime
from enum import Enum
from typing import Optional
from unittest.mock import MagicMock

import pytest

from protean.exceptions import ValidationError
from protean.fields.resolved import ResolvedField, convert_pydantic_errors


# ---------------------------------------------------------------------------
# Tests: Non-dict json_schema_extra
# ---------------------------------------------------------------------------
class TestResolvedFieldNonDictExtra:
    def test_non_dict_json_schema_extra_sets_defaults(self):
        """When json_schema_extra is a callable (not dict), defaults are used."""
        field_info = MagicMock()
        field_info.json_schema_extra = lambda x: x  # non-dict extra
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []

        rf = ResolvedField("test_field", field_info, str)
        assert rf.identifier is False
        assert rf.referenced_as is None
        assert rf.unique is False
        assert rf.increment is False
        assert rf.sanitize is False
        assert rf.field_kind == "standard"
        assert rf._validators == []
        assert rf._error_messages == {}


# ---------------------------------------------------------------------------
# Tests: None field_info defaults
# ---------------------------------------------------------------------------
class TestResolvedFieldNoneFieldInfo:
    def test_none_field_info_defaults(self):
        """None field_info sets safe defaults for all attributes."""
        rf = ResolvedField("test", None, str)
        assert rf.description is None
        assert rf.identifier is False
        assert rf.referenced_as is None
        assert rf.unique is False
        assert rf.increment is False
        assert rf.required is False
        assert rf.default is None


# ---------------------------------------------------------------------------
# Tests: Constraint metadata (Ge, Gt, Le, Lt)
# ---------------------------------------------------------------------------
class TestResolvedFieldConstraints:
    def test_le_constraint(self):
        """Le metadata sets max_value."""
        from annotated_types import Le

        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = [Le(le=100)]

        rf = ResolvedField("price", field_info, float)
        assert rf.max_value == 100

    def test_lt_constraint(self):
        """Lt metadata sets max_value."""
        from annotated_types import Lt

        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = [Lt(lt=50)]

        rf = ResolvedField("score", field_info, int)
        assert rf.max_value == 50

    def test_ge_constraint(self):
        """Ge metadata sets min_value."""
        from annotated_types import Ge

        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = [Ge(ge=0)]

        rf = ResolvedField("count", field_info, int)
        assert rf.min_value == 0

    def test_gt_constraint(self):
        """Gt metadata sets min_value."""
        from annotated_types import Gt

        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = [Gt(gt=1)]

        rf = ResolvedField("positive", field_info, int)
        assert rf.min_value == 1

    def test_no_metadata(self):
        """No metadata yields None constraints."""
        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []

        rf = ResolvedField("name", field_info, str)
        assert rf.max_length is None
        assert rf.min_value is None
        assert rf.max_value is None


# ---------------------------------------------------------------------------
# Tests: content_type property
# ---------------------------------------------------------------------------
class TestResolvedFieldContentType:
    def test_content_type_with_list_int(self):
        """content_type returns inner type for list[int]."""
        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []

        rf = ResolvedField("items", field_info, list[int])
        assert rf.content_type is int

    def test_content_type_with_optional_list(self):
        """Unwrap Optional[list[str]] to get str."""
        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []

        rf = ResolvedField("items", field_info, Optional[list[str]])
        assert rf.content_type is str

    def test_content_type_with_union_list_none(self):
        """Unwrap list[str] | None to get str."""
        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []

        rf = ResolvedField("items", field_info, list[str] | None)
        assert rf.content_type is str

    def test_content_type_non_list_returns_none(self):
        """Non-list type returns None."""
        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []

        rf = ResolvedField("name", field_info, str)
        assert rf.content_type is None

    def test_content_type_bare_list_returns_none(self):
        """list without type args returns None."""
        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []

        rf = ResolvedField("items", field_info, list)
        assert rf.content_type is None


# ---------------------------------------------------------------------------
# Tests: pickled property
# ---------------------------------------------------------------------------
class TestResolvedFieldPickled:
    def test_pickled_always_false(self):
        """pickled property always returns False."""
        rf = ResolvedField("test", None, str)
        assert rf.pickled is False


# ---------------------------------------------------------------------------
# Tests: as_dict
# ---------------------------------------------------------------------------
class TestResolvedFieldAsDict:
    def _make_field(self) -> ResolvedField:
        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []
        return ResolvedField("field", field_info, str)

    def test_as_dict_none(self):
        rf = self._make_field()
        assert rf.as_dict(None) is None

    def test_as_dict_with_to_dict(self):
        """to_dict() is preferred over model_dump()."""
        rf = self._make_field()
        obj = MagicMock()
        obj.to_dict.return_value = {"key": "val"}
        assert rf.as_dict(obj) == {"key": "val"}

    def test_as_dict_with_model_dump(self):
        """model_dump() fallback when no to_dict()."""
        rf = self._make_field()

        class PydanticLike:
            def model_dump(self):
                return {"key": "val"}

        obj = PydanticLike()
        assert rf.as_dict(obj) == {"key": "val"}

    def test_as_dict_with_datetime(self):
        rf = self._make_field()
        dt = datetime.datetime(2024, 1, 1, 12, 0)
        assert rf.as_dict(dt) == str(dt)

    def test_as_dict_with_enum(self):
        """Enum value extraction."""
        rf = self._make_field()

        class Color(Enum):
            RED = "red"
            BLUE = "blue"

        assert rf.as_dict(Color.RED) == "red"

    def test_as_dict_with_list_of_values(self):
        rf = self._make_field()
        result = rf.as_dict([1, 2, 3])
        assert result == [1, 2, 3]

    def test_as_dict_with_list_of_datetimes(self):
        """List of datetimes is recursed."""
        rf = self._make_field()
        now = datetime.datetime.now()
        result = rf.as_dict([now, now])
        assert all(isinstance(r, str) for r in result)

    def test_as_dict_with_plain_value(self):
        rf = self._make_field()
        assert rf.as_dict("hello") == "hello"
        assert rf.as_dict(42) == 42


# ---------------------------------------------------------------------------
# Tests: fail()
# ---------------------------------------------------------------------------
class TestResolvedFieldFail:
    def _make_field(self, name: str = "email") -> ResolvedField:
        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []
        return ResolvedField(name, field_info, str)

    def test_fail_with_known_key(self):
        rf = self._make_field()
        with pytest.raises(ValidationError) as exc_info:
            rf.fail("required")
        assert "email" in exc_info.value.messages

    def test_fail_with_unknown_key(self):
        rf = self._make_field()
        with pytest.raises(ValidationError):
            rf.fail("unknown_key")

    def test_fail_unique_with_formatted_message(self):
        """fail with 'unique' key formats entity_name, field_name, value."""
        rf = self._make_field()
        with pytest.raises(ValidationError) as exc_info:
            rf.fail(
                "unique",
                entity_name="User",
                field_name="email",
                value="test@example.com",
            )
        assert "email" in exc_info.value.messages


# ---------------------------------------------------------------------------
# Tests: get_attribute_name
# ---------------------------------------------------------------------------
class TestResolvedFieldGetAttributeName:
    def test_with_referenced_as(self):
        """Returns referenced_as when set."""
        field_info = MagicMock()
        field_info.json_schema_extra = {"referenced_as": "alt_name"}
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []

        rf = ResolvedField("name", field_info, str)
        assert rf.get_attribute_name() == "alt_name"

    def test_without_referenced_as(self):
        """Returns field_name when no referenced_as."""
        field_info = MagicMock()
        field_info.json_schema_extra = None
        field_info.is_required.return_value = False
        field_info.default = None
        field_info.metadata = []

        rf = ResolvedField("name", field_info, str)
        assert rf.get_attribute_name() == "name"


# ---------------------------------------------------------------------------
# Tests: convert_pydantic_errors
# ---------------------------------------------------------------------------
class TestConvertPydanticErrors:
    def test_field_required_normalization(self):
        """'Field required' is normalized to 'is required'."""
        from pydantic import BaseModel
        from pydantic import ValidationError as PydanticValidationError

        class M(BaseModel):
            name: str

        with pytest.raises(PydanticValidationError) as exc_info:
            M()  # type: ignore[call-arg]

        errors = convert_pydantic_errors(exc_info.value)
        assert errors["name"] == ["is required"]

    def test_value_error_prefix_stripped(self):
        """'Value error, ...' prefix is stripped."""
        from pydantic import BaseModel, model_validator
        from pydantic import ValidationError as PydanticValidationError

        class M(BaseModel):
            x: int = 0

            @model_validator(mode="after")
            def check(self):
                raise ValueError("bad value")

        with pytest.raises(PydanticValidationError) as exc_info:
            M()

        errors = convert_pydantic_errors(exc_info.value)
        # The error should have the prefix stripped
        assert any("bad value" in msg for msgs in errors.values() for msg in msgs)
