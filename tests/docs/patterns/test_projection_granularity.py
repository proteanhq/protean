"""Run the examples on ``docs/patterns/projection-granularity.md``."""

from datetime import UTC, datetime, timedelta

import pytest

from protean import Engine
from protean.exceptions import IncorrectUsageError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example():
    module = load_example("patterns/projection-granularity/001.py")
    with module.domain.domain_context():
        yield module


def _drain(example):
    Engine(example.domain, test_mode=True).run()


def _place_order(example, *, items=("book", "pen")):
    domain = example.domain
    customer = example.Customer(name="Ada", email="ada@example.com")
    domain.repository_for(example.Customer).add(customer)
    order = example.Order(customer_id=customer.id, warehouse_id="east-1", total=30.0)
    order.place(customer, list(items))
    domain.repository_for(example.Order).add(order)
    return customer, order


def _update(example, aggregate_cls, identifier, change):
    repo = example.domain.repository_for(aggregate_cls)
    aggregate = repo.get(identifier)
    change(aggregate)
    repo.add(aggregate)


def test_order_summary_combines_order_and_customer_data(example):
    customer, order = _place_order(example)
    _drain(example)

    summary = example.domain.view_for(example.OrderSummary).get(order.id)
    assert summary.customer_id == customer.id
    assert summary.customer_name == "Ada"
    assert summary.customer_email == "ada@example.com"
    assert summary.status == "placed"
    assert summary.total == 30.0
    assert summary.item_count == 2
    assert summary.placed_at is not None


def test_order_summary_follows_events_from_both_aggregates(example):
    customer, order = _place_order(example)
    _drain(example)
    _update(example, example.Order, order.id, lambda o: o.ship("TRK-1"))
    _update(example, example.Customer, customer.id, lambda c: c.rename("Ada L"))
    _drain(example)

    summary = example.domain.view_for(example.OrderSummary).get(order.id)
    assert summary.status == "shipped"
    assert summary.tracking_number == "TRK-1"
    assert summary.shipped_at is not None
    assert summary.customer_name == "Ada L"


def test_dashboard_counts_move_with_each_status_change(example):
    _, order = _place_order(example)
    _drain(example)
    placed = example.warehouse_dashboard("east-1")
    assert (placed.pending_count, placed.shipped_count, placed.delivered_count) == (
        1,
        0,
        0,
    )

    _update(example, example.Order, order.id, lambda o: o.ship("TRK-1"))
    _drain(example)
    shipped = example.warehouse_dashboard("east-1")
    assert (shipped.pending_count, shipped.shipped_count) == (0, 1)

    _update(example, example.Order, order.id, lambda o: o.deliver())
    _drain(example)
    delivered = example.warehouse_dashboard("east-1")
    assert (delivered.shipped_count, delivered.delivered_count) == (0, 1)


def test_cache_backed_dashboard_has_no_repository(example):
    with pytest.raises(IncorrectUsageError, match="cache-backed"):
        example.domain.repository_for(example.WarehouseDashboard)


def test_order_history_queries_filter_sort_and_count(example):
    now = datetime.now(UTC)
    repo = example.domain.repository_for(example.OrderHistory)
    repo.add(
        example.OrderHistory(
            order_id="o-1",
            customer_id="cust-123",
            status="cancelled",
            placed_at=now - timedelta(days=2),
            cancelled_at=now - timedelta(days=1),
        )
    )
    repo.add(
        example.OrderHistory(
            order_id="o-2",
            customer_id="cust-123",
            status="placed",
            placed_at=now,
        )
    )
    repo.add(
        example.OrderHistory(
            order_id="o-3",
            customer_id="cust-999",
            status="cancelled",
            placed_at=now - timedelta(days=30),
            cancelled_at=now - timedelta(days=20),
        )
    )

    newest_first = [o.order_id for o in example.customer_orders("cust-123")]
    assert newest_first == ["o-2", "o-1"]

    cancelled = example.cancelled_between(now - timedelta(days=3), now)
    assert [o.order_id for o in cancelled] == ["o-1"]
    assert (
        example.cancelled_between(
            now - timedelta(days=3), now - timedelta(days=2)
        ).items
        == []
    )

    assert example.pending_count() == 1


def test_one_order_view_serves_the_list_and_the_detail_endpoint(example):
    now = datetime.now(UTC)
    repo = example.domain.repository_for(example.OrderView)
    repo.add(
        example.OrderView(
            order_id="o-1",
            customer_name="Ada",
            status="shipped",
            total=30.0,
            placed_at=now,
            tracking_number="TRK-1",
            cancellation_reason="none",
        )
    )
    repo.add(
        example.OrderView(
            order_id="o-0",
            customer_name="Grace",
            status="placed",
            total=12.0,
            placed_at=now - timedelta(days=1),
        )
    )

    listing = example.get_orders()
    assert [o["order_id"] for o in listing] == ["o-1", "o-0"]
    assert set(listing[0]) == {
        "order_id",
        "customer_name",
        "status",
        "total",
        "placed_at",
    }

    detail = example.get_order("o-1")
    assert detail["tracking_number"] == "TRK-1"
    assert detail["cancellation_reason"] == "none"


def test_product_is_read_from_its_own_repository(example):
    product = example.Product(name="Lamp", price=25.0)
    example.domain.repository_for(example.Product).add(product)

    assert example.product_detail(product.id).name == "Lamp"


def test_reads_for_one_customer_reach_past_the_default_query_limit(example):
    summaries = example.domain.repository_for(example.OrderSummary)
    history = example.domain.repository_for(example.OrderHistory)
    now = datetime.now(UTC)
    for n in range(130):
        summaries.add(
            example.OrderSummary(
                order_id=f"o-{n}", customer_id="c1", customer_name="Ada"
            )
        )
        history.add(
            example.OrderHistory(
                order_id=f"o-{n}",
                customer_id="c1",
                status="placed",
                placed_at=now - timedelta(minutes=n),
            )
        )

    example.OrderSummaryProjector().on_customer_name_changed(
        example.CustomerNameChanged(customer_id="c1", new_name="Bea")
    )

    view = example.domain.view_for(example.OrderSummary)
    names = {view.get(f"o-{n}").customer_name for n in range(130)}
    assert names == {"Bea"}
    orders = example.customer_orders("c1")
    assert [o.order_id for o in orders] == [f"o-{n}" for n in range(130)]
