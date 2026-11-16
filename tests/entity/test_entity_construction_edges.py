"""Construction and update paths of ``BaseEntity`` that other tests do not reach.

Covers identifier detection in string annotations, a plain ``id``
annotation, ``model_construct`` with no init context on the stack, the order
of keys when construction collects several errors, and ``_update_data``
collecting errors from template dicts and keyword arguments together.
"""

from typing import Annotated

import pytest
from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity, _init_context
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import String, ValueObject


class DoubleQuotedIdentifier(BaseEntity):
    code: 'Annotated[str, Field(json_schema_extra={"identifier": True})]'


class SingleQuotedIdentifier(BaseEntity):
    code: "Annotated[str, Field(json_schema_extra={'identifier': True})]"


class PlainId(BaseEntity):
    id: str = "fixed"
    name: str | None = None


class Address(BaseValueObject):
    street: String(max_length=50)


class Shop(BaseAggregate):
    name: String(max_length=5)
    city: String(max_length=5)
    address = ValueObject(Address, required=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Shop)
    test_domain.register(Address)
    test_domain.init(traverse=False)


class TestAutoIdInjection:
    @pytest.mark.parametrize("cls", [DoubleQuotedIdentifier, SingleQuotedIdentifier])
    def test_identifier_in_a_string_annotation_skips_the_auto_id(self, cls):
        assert list(cls.model_fields) == ["code"]

    def test_a_declared_id_annotation_is_not_replaced(self):
        id_field = PlainId.model_fields["id"]
        assert id_field.default == "fixed"
        assert id_field.json_schema_extra is None


class TestModelConstruct:
    def test_model_construct_runs_post_init_with_no_init_context(self):
        depth = len(getattr(_init_context, "stack", []))

        shop = Shop.model_construct(id="1", name="Corner")

        assert shop.name == "Corner"
        assert shop.address is None
        assert shop.address_street is None
        assert shop._initialized is True
        assert len(getattr(_init_context, "stack", [])) == depth


class TestCollectedErrors:
    def test_a_field_error_comes_before_a_missing_required_value_object(self):
        with pytest.raises(ValidationError) as exc:
            Shop(name="Too long a name")

        assert list(exc.value.messages) == ["name", "address"]
        assert exc.value.messages["address"] == ["is required"]

    def test_update_data_collects_template_and_keyword_errors(self):
        shop = Shop(name="Shop", address=Address(street="Main"))

        with pytest.raises(ValidationError) as exc:
            shop._update_data({"name": "Too long a name"}, city="Too long a city")

        assert list(exc.value.messages) == ["name", "city"]
