"""The examples on the defining fields reference behave as the page says."""

import pytest

from protean.exceptions import ValidationError
from protean.utils.reflection import declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_annotation_style_fields_validate_and_default():
    example = load_example("guides/domain-definition/fields/defining-fields/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.Order(customer_name="John")
        order.add_items(example.LineItem(description="Lamp", unit_price=10.0))
        with pytest.raises(ValidationError) as exc:
            example.LineItem(description="Lamp", quantity=0)

    assert list(declared_fields(example.LineItem))[:3] == [
        "description",
        "quantity",
        "unit_price",
    ]
    assert len(order.items) == 1
    assert order.items[0].quantity == 1
    assert "quantity" in exc.value.messages


def test_assignment_style_fields_validate_and_link_the_manager():
    example = load_example("guides/domain-definition/fields/defining-fields/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        warehouse = example.Warehouse(
            name="Central", capacity=100, manager=example.InventoryManager(name="Ann")
        )
        with pytest.raises(ValidationError) as exc:
            example.Warehouse(name="Central", capacity=-1)

    assert warehouse.capacity == 100
    assert warehouse.manager.warehouse_ref == warehouse.id
    assert "capacity" in exc.value.messages


def test_raw_pydantic_fields_take_their_defaults():
    example = load_example("guides/domain-definition/fields/defining-fields/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        first = example.Metric(name="latency")
        second = example.Metric(name="errors")
        with pytest.raises(ValidationError) as exc:
            example.Metric()

    assert first.score == 0.0
    assert first.metadata == {}
    assert first.metadata is not second.metadata
    assert "name" in exc.value.messages


def test_mixed_styles_validate_the_same_way():
    example = load_example("guides/domain-definition/fields/defining-fields/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        product = example.Product(name="Lamp", sku="LMP-1", price=10.0)
        with pytest.raises(ValidationError) as name_exc:
            example.Product(name="x" * 51)
        with pytest.raises(ValidationError) as price_exc:
            example.Product(name="Lamp", price=-1.0)

    assert set(declared_fields(example.Product)) == {
        "name",
        "sku",
        "price",
        "in_stock",
        "metadata",
        "id",
    }
    assert product.in_stock is True
    assert product.metadata == {}
    assert "name" in name_exc.value.messages
    assert "price" in price_exc.value.messages


def test_assignment_style_works_with_deferred_annotations():
    example = load_example("guides/domain-definition/fields/defining-fields/005.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        product = example.Product(name="Lamp", price=10.0)
        with pytest.raises(ValidationError) as name_exc:
            example.Product(price=10.0)
        with pytest.raises(ValidationError) as price_exc:
            example.Product(name="Lamp", price=-1.0)

    assert product.name == "Lamp"
    assert product.metadata == {}
    assert name_exc.value.messages == {"name": ["is required"]}
    assert "price" in price_exc.value.messages
