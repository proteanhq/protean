"""Run the examples on ``docs/patterns/idempotent-event-handlers.md``."""

from datetime import UTC, datetime

import pytest

from protean.exceptions import ObjectNotFoundError, ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

PLACED_AT = datetime(2026, 1, 5, 9, 30, tzinfo=UTC)
SHIPPED_AT = datetime(2026, 1, 6, 14, 0, tzinfo=UTC)


@pytest.fixture
def strategies():
    example = load_example("patterns/idempotent-event-handlers/001.py")
    # Handlers run only when the test hands them a stored message, as the
    # server would on each delivery.
    example.domain.config["event_processing"] = "async"
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def worked():
    example = load_example("patterns/idempotent-event-handlers/002.py")
    example.domain.config["event_processing"] = "async"
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def _stored(example, aggregate, event):
    """Raise ``event`` on ``aggregate``, save it and return the stored message."""
    aggregate.raise_(event)
    example.domain.repository_for(type(aggregate)).add(aggregate)
    category = type(aggregate).meta_.stream_category
    messages = [
        m
        for m in example.domain.event_store.store.read(category)
        if m.metadata.headers.type == event.__class__.__type__
    ]
    assert messages, f"no {event.__class__.__name__} stored in {category}"
    return messages[-1]


def _order_placed(example, order_id, *, total=40.0, items=()):
    order = example.Order(
        order_id=order_id,
        customer_id="c1",
        customer_name="Ada",
        total=total,
        items=list(items),
    )
    event = example.OrderPlaced(
        order_id=order_id,
        customer_id="c1",
        customer_name="Ada",
        total=total,
        items=list(items),
        placed_at=PLACED_AT,
    )
    return _stored(example, order, event)


def _order_event(example, order_id, event):
    repo = example.domain.repository_for(example.Order)
    try:
        order = repo.get(order_id)
    except ObjectNotFoundError:
        order = example.Order(order_id=order_id, customer_id="c1", total=40.0)
    return _stored(example, order, event)


# Strategy 1: naturally idempotent operations


def test_a_redelivered_order_shipped_leaves_the_status_unchanged(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.OrderStatus)
    repo.add(ex.OrderStatus(order_id="o1"))
    message = _order_event(
        ex,
        "o1",
        ex.OrderShipped(order_id="o1", shipped_at=SHIPPED_AT, tracking_number="TRK1"),
    )

    ex.OrderStatusEventHandler._handle(message)
    after_first = repo.get("o1").to_dict()
    ex.OrderStatusEventHandler._handle(message)

    status = repo.get("o1")
    assert (status.status, status.tracking_number) == ("shipped", "TRK1")
    assert status.shipped_at == SHIPPED_AT
    assert {k: v for k, v in status.to_dict().items() if k != "_version"} == {
        k: v for k, v in after_first.items() if k != "_version"
    }


def test_a_redelivered_order_placed_counts_the_order_once(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.OrderStats)
    repo.add(ex.OrderStats(stats_id="all-orders"))
    message = _order_placed(ex, "o1", total=40.0)

    ex.OrderStatsEventHandler._handle(message)
    ex.OrderStatsEventHandler._handle(message)

    stats = repo.get("all-orders")
    assert stats.order_totals == {"o1": 40.0}
    assert (stats.order_count, stats.total_revenue) == (1, 40.0)


def test_a_second_order_adds_to_the_stats(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.OrderStats)
    repo.add(ex.OrderStats(stats_id="all-orders"))

    ex.OrderStatsEventHandler._handle(_order_placed(ex, "o1", total=40.0))
    ex.OrderStatsEventHandler._handle(_order_placed(ex, "o2", total=15.0))

    stats = repo.get("all-orders")
    assert (stats.order_count, stats.total_revenue) == (2, 55.0)


# Strategy 2: deduplication


def test_check_before_act_reserves_stock_once_per_order(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.Inventory)
    repo.add(ex.Inventory(product_id="p1", available_quantity=10))
    message = _order_placed(ex, "o1", items=[{"product_id": "p1", "quantity": 3}])

    ex.InventoryEventHandler._handle(message)
    ex.InventoryEventHandler._handle(message)

    inventory = repo.get("p1")
    assert inventory.available_quantity == 7
    assert inventory.reserved_for_orders == ["o1"]


def test_check_before_act_reserves_stock_for_a_new_order(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.Inventory)
    repo.add(ex.Inventory(product_id="p1", available_quantity=10))
    items = [{"product_id": "p1", "quantity": 3}]

    ex.InventoryEventHandler._handle(_order_placed(ex, "o1", items=items))
    ex.InventoryEventHandler._handle(_order_placed(ex, "o2", items=items))

    inventory = repo.get("p1")
    assert inventory.available_quantity == 4
    assert inventory.reserved_for_orders == ["o1", "o2"]


def test_a_tracked_event_id_awards_points_once(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.CustomerLoyalty)
    repo.add(ex.CustomerLoyalty(customer_id="c1"))
    message = _order_placed(ex, "o1", total=40.0)

    ex.LoyaltyEventHandler._handle(message)
    ex.LoyaltyEventHandler._handle(message)

    loyalty = repo.get("c1")
    assert loyalty.points == 40
    assert loyalty.processed_events == [message.metadata.headers.id]


def test_an_event_with_a_new_id_awards_points(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.CustomerLoyalty)
    repo.add(ex.CustomerLoyalty(customer_id="c1"))
    first = _order_placed(ex, "o1", total=40.0)
    second = _order_placed(ex, "o2", total=15.0)
    assert first.metadata.headers.id != second.metadata.headers.id

    ex.LoyaltyEventHandler._handle(first)
    ex.LoyaltyEventHandler._handle(second)

    loyalty = repo.get("c1")
    assert loyalty.points == 55
    assert loyalty.processed_events == [
        first.metadata.headers.id,
        second.metadata.headers.id,
    ]


def test_the_global_position_skips_a_repeated_or_older_event(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.ProjectionState)
    repo.add(ex.ProjectionState(state_id="order-projection"))
    first = _order_placed(ex, "o1", total=40.0)
    second = _order_placed(ex, "o2", total=15.0)
    assert first.metadata.event_store.global_position < (
        second.metadata.event_store.global_position
    )

    ex.ProjectionStateHandler._handle(first)
    ex.ProjectionStateHandler._handle(first)
    state = repo.get("order-projection")
    assert (state.order_count, state.total_revenue) == (1, 40.0)

    ex.ProjectionStateHandler._handle(second)
    ex.ProjectionStateHandler._handle(first)

    state = repo.get("order-projection")
    assert (state.order_count, state.total_revenue) == (2, 55.0)
    assert state.last_processed_position == (
        second.metadata.event_store.global_position
    )


def test_the_global_position_drops_an_older_event_retried_after_a_newer_one(
    strategies,
):
    # The subscription moves past a failed event and the recovery pass retries
    # it after newer events have run. The watermark then treats it as seen.
    ex = strategies
    repo = ex.domain.repository_for(ex.ProjectionState)
    repo.add(ex.ProjectionState(state_id="order-projection"))
    failed = _order_placed(ex, "o1", total=40.0)
    later = _order_placed(ex, "o2", total=15.0)

    ex.ProjectionStateHandler._handle(later)
    ex.ProjectionStateHandler._handle(failed)

    state = repo.get("order-projection")
    assert (state.order_count, state.total_revenue) == (1, 15.0)


# Strategy 3: upsert operations


def test_a_redelivered_order_placed_keeps_one_order_summary(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.OrderSummaryProjection)
    message = _order_placed(ex, "o1", total=40.0)

    ex.OrderSummaryProjector._handle(message)
    ex.OrderSummaryProjector._handle(message)

    assert repo.query.all().total == 1
    summary = repo.get("o1")
    assert (summary.customer_name, summary.status) == ("Ada", "placed")
    assert (summary.total, summary.placed_at) == (40.0, PLACED_AT)


def test_a_new_order_gets_its_own_order_summary(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.OrderSummaryProjection)

    ex.OrderSummaryProjector._handle(_order_placed(ex, "o1"))
    ex.OrderSummaryProjector._handle(_order_placed(ex, "o2"))

    assert sorted(s.order_id for s in repo.query.all().items) == ["o1", "o2"]


def _order_paid(ex, order_id):
    items = [{"product_id": "p1", "quantity": 1}]
    return _order_event(
        ex, order_id, ex.OrderPaid(order_id=order_id, customer_id="c1", items=items)
    )


def test_a_redelivered_order_paid_creates_one_shipment(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.Shipment)
    message = _order_paid(ex, "o1")

    ex.ShipmentEventHandler._handle(message)
    ex.ShipmentEventHandler._handle(message)

    shipments = repo.query.all().items
    assert [(s.order_id, s.status) for s in shipments] == [("o1", "pending")]
    assert repo.find_by_order_id("o1").items == [{"product_id": "p1", "quantity": 1}]


def test_a_paid_order_without_a_shipment_gets_one(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.Shipment)

    assert repo.find_by_order_id("o1") is None
    ex.ShipmentEventHandler._handle(_order_paid(ex, "o1"))
    ex.ShipmentEventHandler._handle(_order_paid(ex, "o2"))

    assert sorted(s.order_id for s in repo.query.all().items) == ["o1", "o2"]


# Event handler vs projector idempotency


def test_the_dashboard_projector_gives_the_same_state_on_redelivery(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.OrderDashboardProjection)
    placed = _order_placed(ex, "o1", total=40.0)
    shipped = _order_event(
        ex,
        "o1",
        ex.OrderShipped(order_id="o1", shipped_at=SHIPPED_AT, tracking_number="T"),
    )

    for message in (placed, placed, shipped, shipped):
        ex.OrderDashboardProjector._handle(message)

    assert repo.query.all().total == 1
    dashboard = repo.get("o1")
    assert (dashboard.status, dashboard.total) == ("shipped", 40.0)
    assert (dashboard.placed_at, dashboard.shipped_at) == (PLACED_AT, SHIPPED_AT)


def test_the_dashboard_projector_skips_a_shipment_for_an_unknown_order(strategies):
    ex = strategies
    shipped = _order_event(
        ex,
        "o9",
        ex.OrderShipped(order_id="o9", shipped_at=SHIPPED_AT, tracking_number="T"),
    )

    ex.OrderDashboardProjector._handle(shipped)

    repo = ex.domain.repository_for(ex.OrderDashboardProjection)
    assert repo.query.all().total == 0


def _money_debited(ex, transfer_id, amount):
    source = ex.Account(account_id=f"src-{transfer_id}", balance=100.0)
    event = ex.MoneyDebited(
        account_id=source.account_id,
        target_account_id="b",
        transfer_id=transfer_id,
        amount=amount,
    )
    return _stored(ex, source, event)


def test_a_redelivered_money_debited_credits_the_target_once(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.Account)
    repo.add(ex.Account(account_id="b", balance=10.0))
    message = _money_debited(ex, "t1", 30.0)

    ex.AccountEventHandler._handle(message)
    ex.AccountEventHandler._handle(message)

    target = repo.get("b")
    assert target.balance == 40.0
    assert target.processed_transfers == ["t1"]


def test_a_new_transfer_credits_the_target_again(strategies):
    ex = strategies
    repo = ex.domain.repository_for(ex.Account)
    repo.add(ex.Account(account_id="b", balance=10.0))

    ex.AccountEventHandler._handle(_money_debited(ex, "t1", 30.0))
    ex.AccountEventHandler._handle(_money_debited(ex, "t2", 5.0))

    target = repo.get("b")
    assert target.balance == 45.0
    assert target.processed_transfers == ["t1", "t2"]


# Worked example 1: loyalty points


def test_loyalty_points_are_awarded_once_per_order(worked):
    ex = worked
    repo = ex.domain.repository_for(ex.CustomerLoyalty)
    repo.add(ex.CustomerLoyalty(customer_id="c1"))
    message = _order_placed(ex, "o1", total=40.0)

    ex.LoyaltyEventHandler._handle(message)
    ex.LoyaltyEventHandler._handle(message)

    loyalty = repo.get("c1")
    assert loyalty.points == 40
    assert [(t.source_id, t.amount, t.type) for t in loyalty.point_transactions] == [
        ("o1", 40, "earned")
    ]


def test_loyalty_points_are_awarded_for_a_new_order(worked):
    ex = worked
    repo = ex.domain.repository_for(ex.CustomerLoyalty)
    repo.add(ex.CustomerLoyalty(customer_id="c1"))

    ex.LoyaltyEventHandler._handle(_order_placed(ex, "o1", total=40.0))
    ex.LoyaltyEventHandler._handle(_order_placed(ex, "o2", total=15.0))

    loyalty = repo.get("c1")
    assert loyalty.points == 55
    assert [t.source_id for t in loyalty.point_transactions] == ["o1", "o2"]


# Worked example 2: inventory reservation


def _reserved_events(ex):
    return [
        m
        for m in ex.domain.event_store.store.read(
            f"{ex.Inventory.meta_.stream_category}-p1"
        )
        if m.metadata.headers.type == ex.InventoryReserved.__type__
    ]


def test_stock_is_reserved_once_per_order(worked):
    ex = worked
    repo = ex.domain.repository_for(ex.Inventory)
    repo.add(ex.Inventory(product_id="p1", available_quantity=10))
    message = _order_placed(ex, "o1", items=[{"product_id": "p1", "quantity": 3}])

    ex.InventoryEventHandler._handle(message)
    ex.InventoryEventHandler._handle(message)

    inventory = repo.get("p1")
    assert inventory.available_quantity == 7
    assert [(r.order_id, r.quantity) for r in inventory.reservations] == [("o1", 3)]
    reserved = _reserved_events(ex)
    assert [(m.data["order_id"], m.data["quantity"]) for m in reserved] == [("o1", 3)]


def test_stock_is_reserved_for_a_new_order(worked):
    ex = worked
    repo = ex.domain.repository_for(ex.Inventory)
    repo.add(ex.Inventory(product_id="p1", available_quantity=10))
    items = [{"product_id": "p1", "quantity": 3}]

    ex.InventoryEventHandler._handle(_order_placed(ex, "o1", items=items))
    ex.InventoryEventHandler._handle(_order_placed(ex, "o2", items=items))

    inventory = repo.get("p1")
    assert inventory.available_quantity == 4
    assert [r.order_id for r in inventory.reservations] == ["o1", "o2"]
    assert len(_reserved_events(ex)) == 2


def test_a_reservation_beyond_the_stock_is_rejected(worked):
    ex = worked
    repo = ex.domain.repository_for(ex.Inventory)
    repo.add(ex.Inventory(product_id="p1", available_quantity=2))
    message = _order_placed(ex, "o1", items=[{"product_id": "p1", "quantity": 3}])

    with pytest.raises(ValidationError) as exc:
        ex.InventoryEventHandler._handle(message)

    assert exc.value.messages == {"quantity": ["Insufficient inventory. Available: 2"]}
    inventory = repo.get("p1")
    assert (inventory.available_quantity, inventory.reservations) == (2, [])


# Worked example 3: notification


@pytest.fixture
def sent(worked, monkeypatch):
    calls = []
    monkeypatch.setattr(
        worked,
        "send_email",
        lambda recipient, template: calls.append((recipient, template)),
    )
    return calls


def test_a_redelivered_event_creates_one_notification(worked, sent):
    ex = worked
    repo = ex.domain.repository_for(ex.Notification)
    message = _order_placed(ex, "o1")

    ex.NotificationEventHandler._handle(message)
    ex.NotificationEventHandler._handle(message)

    notifications = repo.query.all().items
    assert [(n.recipient_id, n.type, n.status) for n in notifications] == [
        ("c1", "order_confirmation", "pending")
    ]
    assert notifications[0].source_event_id == message.metadata.headers.id
    assert sent == []


def test_the_sender_sends_each_notification_once(worked, sent):
    ex = worked
    repo = ex.domain.repository_for(ex.Notification)
    message = _order_placed(ex, "o1")
    ex.NotificationEventHandler._handle(message)

    ex.send_pending_notifications()
    ex.send_pending_notifications()
    ex.NotificationEventHandler._handle(message)
    ex.send_pending_notifications()

    assert sent == [("c1", "order_confirmation")]
    [notification] = repo.query.all().items
    assert notification.status == "sent"
    assert notification.sent_at is not None


def test_an_event_with_a_new_id_creates_a_new_notification(worked, sent):
    ex = worked
    repo = ex.domain.repository_for(ex.Notification)

    ex.NotificationEventHandler._handle(_order_placed(ex, "o1"))
    ex.NotificationEventHandler._handle(_order_placed(ex, "o2"))
    ex.send_pending_notifications()

    assert repo.query.all().total == 2
    assert sent == [("c1", "order_confirmation"), ("c1", "order_confirmation")]
