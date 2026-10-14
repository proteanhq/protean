"""Run the examples on ``docs/patterns/publishing-events-to-external-brokers.md``."""

import pytest

from protean.core.unit_of_work import UnitOfWork
from protean.utils.eventing import Message
from tests.docs.support import load_example

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


def test_the_subscriber_ignores_other_event_types():
    consumer = load_example("patterns/publishing-events-to-external-brokers/003.py")
    consumer.fulfillment.init(traverse=False)
    with consumer.fulfillment.domain_context():
        consumer.fulfillment.brokers["default"].publish(
            "myapp::order",
            {
                "data": {"order_id": "o1", "note": "hi"},
                "metadata": {"headers": {"type": "MyApp.OrderNoteAdded.v1"}},
            },
        )
        shipments = (
            consumer.fulfillment.repository_for(consumer.Shipment)
            ._dao.query.all()
            .items
        )

    assert shipments == []
