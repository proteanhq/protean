"""Run the examples on ``docs/patterns/publishing-events-to-external-brokers.md``."""

import pytest

from protean import Engine
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Identifier, String
from protean.utils.eventing import Message
from tests.docs.support import domain_from_config, load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def producer():
    example = load_example("patterns/publishing-events-to-external-brokers/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def _outbox_rows(example, change):
    order = example.Order()
    change(order)
    with UnitOfWork():
        example.domain.repository_for(example.Order).add(order)
    return example.domain._get_outbox_repo("default").find_unprocessed()


def test_the_published_event_is_marked_published():
    example = load_example("patterns/publishing-events-to-external-brokers/001.py")
    example.domain.init(traverse=False)

    assert example.OrderShipped.meta_.published is True


def test_a_published_event_gets_one_outbox_row_per_broker(producer):
    rows = _outbox_rows(producer, lambda order: order.ship("TRK-1"))

    assert sorted(r.target_broker for r in rows) == [
        "analytics_broker",
        "default",
        "fulfillment_broker",
    ]
    assert {r.type for r in rows} == {"MyApp.OrderShipped.v1"}


def test_an_internal_event_gets_only_the_internal_row(producer):
    rows = _outbox_rows(producer, lambda order: order.add_note("Leave at door"))

    assert [(r.type, r.target_broker) for r in rows] == [
        ("MyApp.OrderNoteAdded.v1", "default")
    ]


def test_the_fulfillment_subscriber_creates_a_shipment_from_the_external_message(
    producer,
):
    rows = _outbox_rows(producer, lambda order: order.ship("TRK-1"))
    [row] = [r for r in rows if r.target_broker == "fulfillment_broker"]
    envelope = Message(data=row.data, metadata=row.metadata_).to_external_dict()
    stream = row.metadata_.domain.stream_category

    assert stream == "myapp::order"
    assert "priority" not in envelope["metadata"]["domain"]

    consumer = load_example("patterns/publishing-events-to-external-brokers/003.py")
    consumer.fulfillment.init(traverse=False)
    with consumer.fulfillment.domain_context():
        consumer.fulfillment.brokers["default"].publish(stream, envelope)
        shipments = (
            consumer.fulfillment.repository_for(consumer.Shipment)
            ._dao.query.all()
            .items
        )

    assert [(s.order_id, s.tracking_number) for s in shipments] == [
        (row.data["order_id"], "TRK-1")
    ]


@pytest.mark.parametrize(
    "event_type", ["MyApp.OrderNoteAdded.v1", "MyApp.OrderShippedLate.v1"]
)
def test_the_subscriber_ignores_other_event_types(event_type):
    consumer = load_example("patterns/publishing-events-to-external-brokers/003.py")
    consumer.fulfillment.init(traverse=False)
    with consumer.fulfillment.domain_context():
        consumer.fulfillment.brokers["default"].publish(
            "myapp::order",
            {
                "data": {"order_id": "o1", "tracking_number": "TRK-1"},
                "metadata": {"headers": {"type": event_type}},
            },
        )
        shipments = (
            consumer.fulfillment.repository_for(consumer.Shipment)
            ._dao.query.all()
            .items
        )

    assert shipments == []


ONE_PARTNER = "patterns/publishing-events-to-external-brokers/partner_broker.toml"
TWO_PARTNERS = (
    "patterns/publishing-events-to-external-brokers/two_external_brokers.toml"
)


def _outbox_domain(path, folder):
    """Build a domain from the TOML at ``path`` with inline brokers in place of Redis."""
    domain = domain_from_config(path, folder)
    for broker in domain.config["brokers"].values():
        broker["provider"] = "inline"

    @domain.aggregate
    class Order:
        status: String(default="PLACED")

        def ship(self):
            self.status = "SHIPPED"
            self.raise_(OrderShipped(order_id=self.id))

    @domain.event(part_of=Order, published=True)
    class OrderShipped:
        order_id: Identifier(required=True)

    domain.init(traverse=False)
    return domain, Order


def _shipped_targets(domain, order_cls):
    with domain.domain_context():
        order = order_cls()
        order.ship()
        with UnitOfWork():
            domain.repository_for(order_cls).add(order)
        rows = domain._get_outbox_repo("default").find_unprocessed()
    return sorted(row.target_broker for row in rows)


def _processors(domain, *, external):
    with domain.domain_context():
        engine = Engine(domain, test_mode=True)
    return {
        processor.broker_provider_name: processor
        for processor in engine._outbox_processors.values()
        if processor.is_external is external
    }


@pytest.mark.parametrize(
    "path, targets",
    [
        (ONE_PARTNER, ["default", "partner_events"]),
        (TWO_PARTNERS, ["analytics_broker", "default", "fulfillment_broker"]),
    ],
    ids=["one-partner", "two-partners"],
)
def test_a_published_event_targets_every_configured_broker(tmp_path, path, targets):
    domain, order_cls = _outbox_domain(path, tmp_path)

    assert domain.config["server"]["default_subscription_type"] == "stream"
    assert domain.has_outbox
    assert _shipped_targets(domain, order_cls) == targets


def test_the_outbox_settings_reach_the_external_processor(tmp_path):
    domain, _ = _outbox_domain(ONE_PARTNER, tmp_path)

    assert sorted(_processors(domain, external=False)) == ["default"]
    [(broker, processor)] = _processors(domain, external=True).items()
    assert broker == "partner_events"
    assert processor.messages_per_tick == 50
    assert processor.tick_interval == 1


def test_two_external_brokers_get_one_processor_each(tmp_path):
    domain, _ = _outbox_domain(TWO_PARTNERS, tmp_path)

    assert sorted(_processors(domain, external=False)) == ["default"]
    assert sorted(_processors(domain, external=True)) == [
        "analytics_broker",
        "fulfillment_broker",
    ]
