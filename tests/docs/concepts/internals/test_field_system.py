"""Run the examples on ``docs/concepts/internals/field-system.md``."""

from typing import Literal

import pytest

from protean.exceptions import ValidationError
from protean.fields.spec import FieldSpec
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

_FIELDS = ("name", "price", "status")


def _constraints(field_info):
    # Keep only the constraint objects (MaxLen, Ge, ...). Protean also adds
    # validator callables, which the page's sketch leaves out.
    return {repr(item) for item in field_info.metadata if not hasattr(item, "func")}


def test_field_specs_resolve_to_pydantic_fields():
    example = load_example("concepts/internals/field-system/001.py")
    fields = example.Product.model_fields

    assert not any(isinstance(fields[name].annotation, FieldSpec) for name in _FIELDS)
    assert fields["name"].annotation is str
    assert fields["name"].is_required()
    assert fields["price"].annotation is float
    assert fields["price"].default == 0.0
    assert fields["status"].annotation == Literal["active", "discontinued"]
    assert fields["status"].default == "active"


def test_what_pydantic_sees_matches_what_you_write():
    written = load_example("concepts/internals/field-system/001.py").Product
    resolved = load_example("concepts/internals/field-system/002.py").Product

    for name in _FIELDS:
        mine, theirs = written.model_fields[name], resolved.model_fields[name]
        assert mine.annotation == theirs.annotation
        assert mine.is_required() == theirs.is_required()
        assert mine.default == theirs.default
        assert _constraints(mine) == _constraints(theirs)


def test_constraints_are_enforced():
    example = load_example("concepts/internals/field-system/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        product = example.Product(name="Widget")
        assert (product.price, product.status) == (0.0, "active")

        with pytest.raises(ValidationError) as exc:
            example.Product()
        assert exc.value.messages == {"name": ["is required"]}

        with pytest.raises(ValidationError) as exc:
            example.Product(name="x" * 51)
        assert exc.value.messages == {
            "name": ["String should have at most 50 characters"]
        }

        with pytest.raises(ValidationError) as exc:
            example.Product(name="Widget", price=-1)
        assert exc.value.messages == {
            "price": ["Input should be greater than or equal to 0"]
        }

        with pytest.raises(ValidationError) as exc:
            example.Product(name="Widget", status="retired")
        assert exc.value.messages == {
            "status": ["Input should be 'active' or 'discontinued'"]
        }


def test_constraints_map_to_json_schema_keywords():
    example = load_example("concepts/internals/field-system/001.py")
    properties = example.Product.model_json_schema()["properties"]

    assert properties["name"]["maxLength"] == 50
    assert properties["price"]["minimum"] == 0
    assert properties["status"]["enum"] == ["active", "discontinued"]
    # choices make max_length redundant for validation, but it stays for the
    # database column size
    assert properties["status"]["maxLength"] == 255


def test_the_three_definition_styles_all_become_fields():
    example = load_example("concepts/internals/field-system/003.py")
    fields = example.Product.model_fields

    assert {"name", "price", "metadata"} <= set(fields)
    assert fields["name"].annotation == str | None
    assert fields["price"].annotation == float | None
    assert fields["metadata"].annotation is dict
    # The raw Pydantic field passes through untouched
    assert fields["metadata"].default_factory is dict

    example.domain.init(traverse=False)
    with example.domain.domain_context():
        first, second = example.Product(), example.Product()
        assert first.metadata == {}
        assert first.metadata is not second.metadata

        # The assignment-style field keeps its min_value constraint
        assert example.Product(price=0.0).price == 0.0
        with pytest.raises(ValidationError) as exc:
            example.Product(price=-1)
        assert exc.value.messages == {
            "price": ["Input should be greater than or equal to 0"]
        }

        with pytest.raises(ValidationError) as exc:
            example.Product(name="x" * 51)
        assert exc.value.messages == {
            "name": ["String should have at most 50 characters"]
        }
