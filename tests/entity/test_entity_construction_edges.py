"""Construction and update paths of ``BaseEntity`` that other tests do not reach.

Covers identifier detection in string annotations, a plain ``id``
annotation, ``model_construct`` with no init context on the stack, the order
of keys when construction collects several errors, and ``_update_data``
collecting errors from template dicts and keyword arguments together. Also
checks that a subclass method named like a module-level construction helper
does not replace that helper.
"""

from typing import Annotated

import pytest
from pydantic import Field

from protean.core import entity as entity_module
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity, _init_context
from protean.core.projection import BaseProjection
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import HasMany, Identifier, String, ValueObject


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
    def test_identifier_in_a_double_quoted_string_annotation_skips_the_auto_id(self):
        class DoubleQuotedIdentifier(BaseEntity):
            code: 'Annotated[str, Field(json_schema_extra={"identifier": True})]'

        assert list(DoubleQuotedIdentifier.model_fields) == ["code"]

    def test_identifier_in_a_single_quoted_string_annotation_skips_the_auto_id(self):
        class SingleQuotedIdentifier(BaseEntity):
            code: "Annotated[str, Field(json_schema_extra={'identifier': True})]"

        assert list(SingleQuotedIdentifier.model_fields) == ["code"]

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

    def test_update_data_collects_errors_for_one_field_from_both_sources(self):
        shop = Shop(name="Shop", address=Address(street="Main"))

        with pytest.raises(ValidationError) as exc:
            shop._update_data({"name": "Too long a name"}, name="Another long name")

        assert len(exc.value.messages["name"]) == 2


def _replaced_helper(*args, **kwargs):
    raise AssertionError("a subclass method replaced a framework helper")


# Every module-level helper in ``protean.core.entity``, as a method that raises.
_SAME_NAMED_METHODS = {
    name: _replaced_helper
    for name, obj in vars(entity_module).items()
    if name.startswith("_")
    and not name.startswith("__")
    and callable(obj)
    and getattr(obj, "__module__", None) == entity_module.__name__
    and not isinstance(obj, type)
    and name not in vars(BaseEntity)
}


class TestSubclassMethodsDoNotReplaceHelpers:
    def test_the_attack_covers_the_init_helpers(self):
        assert {
            "_split_init_values",
            "_apply_hierarchy",
            "_rebuild_value_objects",
            "_write_shadow_values",
            "_set_descriptor_field",
            "_precheck_model_field",
            "_run_own_invariants",
        } <= set(_SAME_NAMED_METHODS)

    def test_aggregate_and_entity_build_and_update_normally(self, test_domain):
        line_cls = type(
            "ShadowingLine",
            (BaseEntity,),
            {"sku": String(max_length=10), **_SAME_NAMED_METHODS},
        )
        order_cls = type(
            "ShadowingOrder",
            (BaseAggregate,),
            {
                "name": String(max_length=10),
                "address": ValueObject(Address),
                "lines": HasMany(line_cls),
                **_SAME_NAMED_METHODS,
            },
        )
        test_domain.register(order_cls)
        test_domain.register(line_cls, part_of=order_cls)
        test_domain.init(traverse=False)

        order = order_cls(
            name="First", address_street="Main", lines=[line_cls(sku="A1")]
        )
        order.name = "Second"
        order.address = Address(street="High")
        order.add_lines(line_cls(sku="B2"))

        assert order.name == "Second"
        assert order.address_street == "High"
        assert [line.sku for line in order.lines] == ["A1", "B2"]
        assert order.lines[0]._root is order

    def test_projection_builds_normally(self, test_domain):
        view_cls = type(
            "ShadowingView",
            (BaseProjection,),
            {
                "view_id": Identifier(identifier=True),
                "address": ValueObject(Address),
                **_SAME_NAMED_METHODS,
            },
        )
        test_domain.register(view_cls)
        test_domain.init(traverse=False)

        view = view_cls(view_id="1", address_street="Main")

        assert view.address == Address(street="Main")
