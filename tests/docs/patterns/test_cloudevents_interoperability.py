"""Run the examples on ``docs/patterns/cloudevents-interoperability.md``."""

import json

import pytest

from protean.utils.eventing import Message
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

STRIPE_EVENT = {
    "specversion": "1.0",
    "id": "evt-1",
    "type": "com.stripe.payment.succeeded",
    "source": "https://stripe.com",
    "data": {"payment_intent_id": "pi_1", "amount": 42.0},
}


@pytest.fixture
def orders():
    example = load_example("patterns/cloudevents-interoperability/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


def _place_order(example):
    order = example.Order(total=99.5)
    order.place()
    example.domain.repository_for(example.Order).add(order)
    [(topic, value)] = example.kafka_producer.sent
    return order, topic, json.loads(value)


def test_the_publisher_sends_a_cloudevent_to_the_order_events_topic(orders):
    order, topic, cloud_event = _place_order(orders)

    assert topic == "order-events"
    assert cloud_event["specversion"] == "1.0"
    assert cloud_event["type"] == "Orders.OrderPlaced.v1"
    assert cloud_event["source"] == "urn:protean:orders"
    assert cloud_event["id"]
    assert cloud_event["data"] == {"order_id": order.order_id, "total": 99.5}


def test_a_configured_source_uri_replaces_the_derived_source(orders):
    orders.domain.config["source_uri"] = "https://orders.example.com"

    _, _, cloud_event = _place_order(orders)

    assert cloud_event["source"] == "https://orders.example.com"


def test_the_cloudevent_round_trips_into_the_domain_event(orders):
    order, _, cloud_event = _place_order(orders)

    message = Message.from_cloudevent(cloud_event)
    event = message.to_domain_object()

    assert isinstance(event, orders.OrderPlaced)
    assert (event.order_id, event.total) == (order.order_id, 99.5)
    assert message.metadata.headers.id == cloud_event["id"]
    assert message.metadata.envelope.checksum == cloud_event["proteanchecksum"]


def _payments(payload):
    example = load_example("patterns/cloudevents-interoperability/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        example.domain.brokers["default"].publish("payment-webhooks", payload)
        return example.domain.repository_for(example.Payment)._dao.query.all().items


def test_the_webhook_subscriber_confirms_a_stripe_payment():
    payments = _payments(STRIPE_EVENT)

    assert [(p.payment_id, p.amount) for p in payments] == [("pi_1", 42.0)]


def test_the_webhook_subscriber_ignores_other_cloudevent_types():
    payments = _payments({**STRIPE_EVENT, "type": "com.stripe.payment.failed"})

    assert payments == []


def test_correlation_causation_and_checksum_survive_the_shared_topic_round_trip():
    example = load_example("patterns/cloudevents-interoperability/003.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        command = example.PlaceOrder(total=12.5)
        example.domain.process(command, correlation_id="corr-1")
        [stored] = example.domain.event_store.store.read("orders::order")

        event = example.consume(example.domain.brokers["default"])

    assert isinstance(event, example.OrderPlaced)
    assert event.total == 12.5
    assert event._metadata.headers.id == stored.metadata.headers.id
    assert event._metadata.domain.correlation_id == "corr-1"
    assert event._metadata.domain.causation_id == stored.metadata.domain.causation_id
    assert event._metadata.domain.causation_id
    assert event._metadata.envelope.checksum == stored.metadata.envelope.checksum
