"""Tests for #1139: the ``renamed_from`` field metadata.

Covers normalization, the kwarg on the classic ``Field`` (with clone
preservation) and on ``FieldSpec`` (threaded through ``json_schema_extra`` and
preserved across ``copy.copy``).
"""

import copy

import pytest

from protean.fields import String
from protean.fields.base import Field, normalize_field_renamed_from


class ConcreteField(Field):
    """Minimal concrete classic Field subclass (Field is abstract)."""

    def _cast_to_type(self, value):
        return value

    def as_dict(self, value):
        return value


class TestNormalizeRenamedFrom:
    def test_none_returns_none(self):
        assert normalize_field_renamed_from(None) is None

    def test_string_becomes_single_element_list(self):
        assert normalize_field_renamed_from("old_name") == ["old_name"]

    def test_list_is_kept(self):
        assert normalize_field_renamed_from(["a", "b"]) == ["a", "b"]

    def test_tuple_becomes_list(self):
        assert normalize_field_renamed_from(("a", "b")) == ["a", "b"]

    def test_empty_list_returns_none(self):
        assert normalize_field_renamed_from([]) is None

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="Invalid `renamed_from` value"):
            normalize_field_renamed_from(42)

    def test_empty_string_alias_raises(self):
        with pytest.raises(ValueError, match="non-empty field-name string"):
            normalize_field_renamed_from(["a", ""])

    def test_non_string_alias_raises(self):
        with pytest.raises(ValueError, match="non-empty field-name string"):
            normalize_field_renamed_from(["a", 5])


class TestClassicFieldRenamedFrom:
    def test_field_stores_single_alias_as_list(self):
        assert ConcreteField(renamed_from="old").renamed_from == ["old"]

    def test_field_stores_multiple_aliases(self):
        assert ConcreteField(renamed_from=["a", "b"]).renamed_from == ["a", "b"]

    def test_field_without_renamed_from_is_none(self):
        assert ConcreteField().renamed_from is None

    def test_clone_preserves_renamed_from(self):
        field = ConcreteField(renamed_from=["a", "b"])
        assert field._clone().renamed_from == ["a", "b"]


class TestFieldSpecRenamedFrom:
    """``String()`` (and the other field factories) return a ``FieldSpec``."""

    def test_normalizes_renamed_from(self):
        assert String(renamed_from="old").renamed_from == ["old"]

    def test_without_renamed_from_is_none(self):
        assert String().renamed_from is None

    def test_renamed_from_in_json_schema_extra(self):
        extra = (
            String(renamed_from=["old"])
            .resolve_field_kwargs()
            .get("json_schema_extra", {})
        )
        assert extra.get("_renamed_from") == ["old"]

    def test_no_renamed_from_key_when_unset(self):
        extra = String().resolve_field_kwargs().get("json_schema_extra", {})
        assert "_renamed_from" not in extra

    def test_copy_preserves_renamed_from(self):
        assert copy.copy(String(renamed_from=["a", "b"])).renamed_from == ["a", "b"]
