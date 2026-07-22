"""Field-level tests for the ``auto_now`` / ``auto_now_add`` DateTime flags.

These cover declaration-time behavior only (validation, carried metadata, and
the Optional-until-saved shape). The save-time stamping is exercised in
``tests/aggregate/test_pre_persist_lifecycle.py``.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import ValidationError
from protean.fields import Date, DateTime, Integer, String
from protean.utils.reflection import fields


class Widget(BaseAggregate):
    name: String(max_length=50)
    created_at: DateTime(auto_now_add=True)
    updated_at: DateTime(auto_now=True)
    on_date: Date(auto_now=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Widget)
    test_domain.init(traverse=False)


def test_auto_now_metadata_is_carried_onto_the_resolved_field():
    widget_fields = fields(Widget)

    assert widget_fields["created_at"].auto_now_add is True
    assert widget_fields["created_at"].auto_now is False
    assert widget_fields["updated_at"].auto_now is True
    assert widget_fields["updated_at"].auto_now_add is False
    assert widget_fields["on_date"].auto_now is True


def test_plain_fields_default_to_no_auto_now():
    assert fields(Widget)["name"].auto_now is False
    assert fields(Widget)["name"].auto_now_add is False


def test_auto_now_fields_are_optional_and_unset_before_save():
    # The framework stamps them at save time, so they are None on a fresh
    # in-memory instance (unlike a construction-time ``default=utc_now``).
    widget = Widget(name="gadget")

    assert widget.created_at is None
    assert widget.updated_at is None
    assert widget.on_date is None


@pytest.mark.parametrize("factory", [String, Integer])
def test_auto_now_rejected_on_non_temporal_fields(factory):
    with pytest.raises(ValidationError):
        factory(auto_now=True)

    with pytest.raises(ValidationError):
        factory(auto_now_add=True)


def test_auto_now_and_auto_now_add_are_mutually_exclusive():
    with pytest.raises(ValidationError):
        DateTime(auto_now=True, auto_now_add=True)


def test_auto_now_fields_cannot_be_required():
    # The value is stamped at save time, so a required auto_now field would be
    # impossible to construct. Reject it at declaration.
    with pytest.raises(ValidationError):
        DateTime(auto_now=True, required=True)

    with pytest.raises(ValidationError):
        DateTime(auto_now_add=True, required=True)


def test_auto_now_allowed_on_date_fields():
    # Both flags are valid on a Date field (no exception at declaration).
    assert Date(auto_now=True) is not None
    assert Date(auto_now_add=True) is not None


def test_resolved_field_defaults_auto_now_when_metadata_is_non_dict():
    # A raw Pydantic FieldInfo may carry a *callable* json_schema_extra rather
    # than a dict; ResolvedField then falls back to defaults (auto_now=False).
    from pydantic.fields import FieldInfo

    from protean.fields.resolved import ResolvedField

    field_info = FieldInfo(annotation=str, json_schema_extra=lambda schema: None)
    resolved = ResolvedField("x", field_info, str)

    assert resolved.auto_now is False
    assert resolved.auto_now_add is False
