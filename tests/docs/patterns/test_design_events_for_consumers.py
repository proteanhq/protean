"""Run the examples on ``docs/patterns/design-events-for-consumers.md``."""

from datetime import UTC, datetime

import pytest

from protean.utils.eventing import Message
from protean.utils.reflection import declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _context(example):
    domain = example.domain
    domain.init(traverse=False)
    return domain.domain_context()


def _event_types(example, stream):
    return [
        m.metadata.headers.type for m in example.domain.event_store.store.read(stream)
    ]


def _fields(cls):
    return set(declared_fields(cls)) - {"_metadata"}


# Delta events


@pytest.mark.parametrize(
    "cls_name, expected",
    [
        (
            "OrderPlaced",
            {
                "order_id",
                "customer_id",
                "customer_name",
                "customer_email",
                "items",
                "total",
                "placed_at",
            },
        ),
        (
            "OrderShipped",
            {
                "order_id",
                "customer_id",
                "customer_email",
                "tracking_number",
                "carrier",
                "shipped_at",
            },
        ),
        (
            "OrderItemAdded",
            {
                "order_id",
                "product_id",
                "product_name",
                "quantity",
                "unit_price",
                "new_total",
            },
        ),
    ],
)
def test_each_delta_event_carries_the_data_of_its_change(cls_name, expected):
    example = load_example("patterns/design-events-for-consumers/001.py")
    with _context(example):
        cls = getattr(example, cls_name)
        assert _fields(cls) == expected
        assert all(declared_fields(cls)[name].required for name in expected)


# Fact events


def test_saving_a_fact_event_aggregate_writes_its_whole_state():
    example = load_example("patterns/design-events-for-consumers/002.py")
    with _context(example):
        domain = example.domain
        order = example.Order(
            order_id="o1",
            customer_id="c1",
            items=[example.OrderItem(product_id="p1", quantity=2)],
            total=19.5,
        )
        domain.repository_for(example.Order).add(order)

        messages = domain.event_store.store.read("facteventorders::order-fact-o1")
        assert len(messages) == 1
        fact = messages[0]
        assert fact.metadata.headers.type == "FactEventOrders.OrderFactEvent.v1"
        assert fact.data["order_id"] == "o1"
        assert fact.data["customer_id"] == "c1"
        assert fact.data["status"] == "draft"
        assert fact.data["total"] == 19.5
        assert [(i["product_id"], i["quantity"]) for i in fact.data["items"]] == [
            ("p1", 2)
        ]


# Delta and fact events on one aggregate


def test_placing_raises_the_delta_event_and_saving_adds_the_fact_event():
    example = load_example("patterns/design-events-for-consumers/003.py")
    with _context(example):
        domain = example.domain
        order = example.Order(
            order_id="o1",
            customer_id="c1",
            customer_email="ada@example.com",
            items=[example.OrderItem(product_id="p1", quantity=2)],
            total=19.5,
        )
        order.place()
        domain.repository_for(example.Order).add(order)

        placed = domain.event_store.store.read("deltaandfactevents::order-o1")
        assert len(placed) == 1
        assert placed[0].metadata.headers.type == "DeltaAndFactEvents.OrderPlaced.v1"
        assert placed[0].data["customer_email"] == "ada@example.com"
        assert placed[0].data["total"] == 19.5
        assert [i["product_id"] for i in placed[0].data["items"]] == ["p1"]

        assert _event_types(example, "deltaandfactevents::order-fact-o1") == [
            "DeltaAndFactEvents.OrderFactEvent.v1"
        ]
        fact = domain.event_store.store.read("deltaandfactevents::order-fact-o1")[0]
        assert fact.data["status"] == "placed"


# Identifiers for every referenced aggregate


def test_event_carries_an_identifier_for_each_aggregate_it_refers_to():
    example = load_example("patterns/design-events-for-consumers/004.py")
    with _context(example):
        fields = declared_fields(example.OrderPlaced)
        assert _fields(example.OrderPlaced) == {
            "order_id",
            "customer_id",
            "shipping_address_id",
        }
        assert all(
            fields[name].field_kind == "identifier"
            for name in _fields(example.OrderPlaced)
        )
        assert fields["shipping_address_id"].required is False


# Enough context for every consumer


def test_event_declares_exactly_the_fields_its_consumers_need():
    example = load_example("patterns/design-events-for-consumers/005.py")
    with _context(example):
        assert _fields(example.OrderPlaced) == {
            "order_id",
            "customer_id",
            "customer_name",
            "customer_email",
            "items",
            "total",
            "placed_at",
        }
        event = example.OrderPlaced(
            order_id="o1",
            customer_id="c1",
            customer_name="Ada",
            customer_email="ada@example.com",
            items=[{"product_id": "p1", "quantity": 2}],
            total=19.5,
            placed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert event.customer_email == "ada@example.com"


# Cross-aggregate data at event time


def test_command_data_reaches_the_event_without_loading_the_customer():
    example = load_example("patterns/design-events-for-consumers/006.py")
    with _context(example):
        domain = example.domain
        domain.repository_for(example.Order).add(
            example.Order(
                order_id="o1",
                customer_id="c1",
                items=[example.OrderItem(product_id="p1", quantity=2)],
                total=19.5,
            )
        )

        domain.process(
            example.PlaceOrder(
                order_id="o1", customer_name="Ada", customer_email="ada@example.com"
            )
        )

        assert domain.repository_for(example.Order).get("o1").status == "placed"
        placed = [
            m
            for m in domain.event_store.store.read("crossaggregateeventdata::order-o1")
            if m.metadata.headers.type == "CrossAggregateEventData.OrderPlaced.v1"
        ]
        assert len(placed) == 1
        data = placed[0].data
        assert (data["customer_id"], data["customer_name"], data["customer_email"]) == (
            "c1",
            "Ada",
            "ada@example.com",
        )
        assert data["total"] == 19.5


# Projection-driven event design


def test_projector_builds_the_summary_from_event_data_alone():
    example = load_example("patterns/design-events-for-consumers/007.py")
    with _context(example):
        domain = example.domain
        placed_at = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        shipped_at = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
        order = example.Order(order_id="o1", customer_name="Ada")
        order.raise_(
            example.OrderPlaced(
                order_id="o1",
                customer_name="Ada",
                items=[{"product_id": "p1"}, {"product_id": "p2"}],
                total=30.0,
                placed_at=placed_at,
            )
        )
        domain.repository_for(example.Order).add(order)

        repo = domain.repository_for(example.OrderSummaryProjection)
        summary = repo.get("o1")
        assert (summary.customer_name, summary.status) == ("Ada", "placed")
        assert (summary.item_count, summary.total) == (2, 30.0)
        assert summary.placed_at == placed_at
        assert summary.shipped_at is None

        order = domain.repository_for(example.Order).get("o1")
        order.raise_(example.OrderShipped(order_id="o1", shipped_at=shipped_at))
        domain.repository_for(example.Order).add(order)

        summary = repo.get("o1")
        assert summary.status == "shipped"
        assert summary.shipped_at == shipped_at
        assert summary.item_count == 2


# Cross-domain events


def test_fulfillment_subscriber_creates_a_shipment_from_the_event_payload():
    ordering = load_example("patterns/design-events-for-consumers/008.py")
    fulfillment = load_example("patterns/design-events-for-consumers/009.py")
    ordering.domain.init(traverse=False)
    with ordering.domain.domain_context():
        event = ordering.OrderPlaced(
            order_id="o1",
            customer_id="c1",
            customer_email="ada@example.com",
            items=[{"product_id": "p1", "quantity": 2}],
            total=19.5,
            currency="USD",
            placed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        envelope = Message.from_domain_object(event).to_external_dict()

    with _context(fulfillment):
        assert fulfillment.OrderEventsSubscriber.meta_.stream == "orders"
        fulfillment.domain.brokers["default"].publish("orders", envelope)

        shipments = (
            fulfillment.domain.repository_for(fulfillment.Shipment).query.all().items
        )
        assert len(shipments) == 1
        assert (shipments[0].order_id, shipments[0].customer_id) == ("o1", "c1")
        assert shipments[0].items == [{"product_id": "p1", "quantity": 2}]


# When thin events are acceptable


def test_thin_events_carry_only_the_order_and_the_reason():
    example = load_example("patterns/design-events-for-consumers/010.py")
    with _context(example):
        assert _fields(example.OrderProjectionStale) == {"order_id"}
        assert _fields(example.OrderCancelled) == {"order_id", "reason"}
        assert example.Order.meta_.fact_events is True
        assert "order_id" in declared_fields(example.Order._fact_event_cls)
