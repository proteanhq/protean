"""The examples on the projections guide behave as the page says."""

import pytest

from protean.exceptions import NotSupportedError, ObjectNotFoundError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def inventory():
    """The example module after its own sections ran, records included."""
    example = load_example("guides/consume-state/projections/001.py")
    with example.domain.domain_context():
        yield example


@pytest.fixture
def catalog():
    example = load_example("guides/consume-state/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def test_projector_writes_the_product_added_values_to_the_projection(catalog):
    product = catalog.Product.create(
        name="Laptop",
        description="High-performance laptop",
        price=999.99,
        stock_quantity=50,
    )
    catalog.domain.repository_for(catalog.Product).add(product)

    record = catalog.domain.view_for(catalog.ProductInventory).get(product.id)

    assert record.product_id == product.id
    assert record.name == "Laptop"
    assert record.description == "High-performance laptop"
    assert record.price == 999.99
    assert record.stock_quantity == 50
    assert record.last_updated is not None


def test_projector_updates_the_stock_after_stock_adjusted(catalog):
    product = catalog.Product.create(
        name="Laptop",
        description="High-performance laptop",
        price=999.99,
        stock_quantity=50,
    )
    repo = catalog.domain.repository_for(catalog.Product)
    repo.add(product)

    product.adjust_stock(-30)
    repo.add(product)

    record = catalog.domain.view_for(catalog.ProductInventory).get(product.id)
    assert record.stock_quantity == 20


def test_view_reads_the_record_by_identifier_and_by_criteria(inventory):
    view = inventory.domain.view_for(inventory.ProductInventory)

    item = view.get("abc-123")
    assert item.name == "Keyboard"
    assert item.stock_quantity == 4
    assert view.find_by(product_id="abc-123").name == "Keyboard"
    assert view.exists("abc-123") is True
    assert view.exists("no-such-id") is False


def test_example_reads_back_the_record_it_wrote(inventory):
    assert inventory.item.name == "Keyboard"
    assert inventory.item.stock_quantity == 4
    assert inventory.found is True
    assert [item.name for item in inventory.results] == ["Keyboard"]
    assert inventory.inventory_record.name == "Mouse"
    assert inventory.inventory_record.stock_quantity == 12


def test_write_path_adds_a_second_record(inventory):
    view = inventory.domain.view_for(inventory.ProductInventory)

    assert view.get("def-456").name == "Mouse"
    assert view.count() == 2
    assert [item.name for item in view.query.order_by("name").all()] == [
        "Keyboard",
        "Mouse",
    ]


def test_filter_skips_records_at_or_above_the_threshold(inventory):
    view = inventory.domain.view_for(inventory.ProductInventory)

    low_stock = view.query.filter(stock_quantity__lt=10).all()

    assert [item.product_id for item in low_stock] == ["abc-123"]


def test_get_raises_for_a_missing_record(inventory):
    view = inventory.domain.view_for(inventory.ProductInventory)

    with pytest.raises(ObjectNotFoundError):
        view.get("no-such-id")


def test_query_blocks_updates_and_deletes(inventory):
    view = inventory.domain.view_for(inventory.ProductInventory)

    with pytest.raises(NotSupportedError):
        view.query.filter(product_id="abc-123").update(stock_quantity=0)
    with pytest.raises(NotSupportedError):
        view.query.filter(product_id="abc-123").delete()


def test_limit_defaults_to_100_and_the_decorator_overrides_it(inventory):
    assert inventory.ProductInventory.meta_.limit == 100
    assert inventory.LargeReport.meta_.limit == 500


def test_the_per_query_limit_overrides_the_decorator(inventory):
    assert inventory.reports.page_size == 1000


def test_the_pages_pagination_query_lands_past_its_one_record(inventory):
    # The pagination section runs before the write section adds the mouse.
    assert inventory.page.page == 3
    assert inventory.page_size == 20
    assert inventory.number == 3
    assert inventory.page.total == 1
    assert inventory.items == []
    assert inventory.total_pages == 1


def test_pagination_reports_the_page_position(inventory):
    page = (
        inventory.domain.view_for(inventory.ProductInventory)
        .query.order_by("name")
        .limit(1)
        .offset(1)
        .all()
    )

    assert [item.name for item in page.items] == ["Mouse"]
    assert page.total == 2
    assert page.page == 2
    assert page.page_size == 1
    assert page.total_pages == 2
    assert page.has_prev is True
    assert page.has_next is False


def test_value_object_field_is_queryable_by_its_shadow_field(inventory):
    assert [order.order_id for order in inventory.springfield_orders] == ["order-1"]
    assert inventory.springfield_orders.first.shipping_address.city == "Springfield"
    assert inventory.springfield_orders.first.shipping_address.street == "1 Main St"
