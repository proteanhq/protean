"""Run the examples on ``docs/patterns/sharing-event-classes-across-domains.md``."""

import pytest

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import Auto
from protean.utils.eventing import Message
from protean.utils.reflection import declared_fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _fields(cls):
    return set(declared_fields(cls)) - {"_metadata"}


def _context(example):
    example.domain.init(traverse=False)
    return example.domain.domain_context()


def test_the_consumer_declares_a_subset_of_the_publisher_fields():
    example = load_example("patterns/sharing-event-classes-across-domains/001.py")

    consumer = _fields(example.ExternalOrderPlaced)
    assert consumer == {"order_id", "customer_id", "items"}
    assert consumer < _fields(example.OrderPlaced)


def test_the_publisher_contract_test_passes_against_the_order_aggregate():
    example = load_example("patterns/sharing-event-classes-across-domains/002.py")
    with _context(example):
        example.TestOrderPlacedContract().test_order_placed_has_required_fields(
            test_domain=example.domain
        )


def test_the_published_event_carries_the_item_list():
    example = load_example("patterns/sharing-event-classes-across-domains/002.py")
    with _context(example):
        order = example.Order(customer_id="cust-123", total=100.0)
        order.add_items(example.OrderItem(product_id="prod-1", quantity=2))
        order.place()

    assert order._events[0].to_dict()["items"] == [
        {"product_id": "prod-1", "quantity": 2}
    ]


def test_the_consumer_contract_test_passes_on_a_payload_with_extra_fields():
    example = load_example("patterns/sharing-event-classes-across-domains/003.py")
    with _context(example):
        example.TestExternalOrderPlacedConsumption().test_can_deserialize_order_placed(
            test_domain=example.domain
        )


def test_the_consumer_reads_the_payload_the_publisher_raises():
    publisher = load_example("patterns/sharing-event-classes-across-domains/002.py")
    with _context(publisher):
        order = publisher.Order(customer_id="cust-123", total=100.0)
        order.add_items(publisher.OrderItem(product_id="prod-1", quantity=2))
        order.place()
    payload = order._events[0].to_dict()

    consumer = load_example("patterns/sharing-event-classes-across-domains/003.py")
    known = _fields(consumer.ExternalOrderPlaced)
    with _context(consumer):
        event = consumer.ExternalOrderPlaced(
            **{key: value for key, value in payload.items() if key in known}
        )

    assert event.order_id == str(order.id)
    assert event.customer_id == "cust-123"
    assert event.items == [{"product_id": "prod-1", "quantity": 2}]


def test_the_consumer_class_rejects_fields_it_does_not_declare():
    example = load_example("patterns/sharing-event-classes-across-domains/003.py")
    with _context(example), pytest.raises(ValidationError) as exc:
        example.ExternalOrderPlaced(
            order_id="ord-1", customer_id="cust-1", items=[], total=75.0
        )

    assert "total" in exc.value.messages


def test_the_shared_kernel_event_works_once_a_domain_registers_it():
    example = load_example("patterns/sharing-event-classes-across-domains/004.py")
    domain = Domain(name="SharedKernel")

    @domain.aggregate
    class Order:
        order_id: Auto(identifier=True)

    domain.register(example.OrderPlacedEvent, part_of=Order)
    domain.init(traverse=False)
    with domain.domain_context():
        event = example.OrderPlacedEvent(
            order_id="o1", customer_id="c1", items=["a"], total=5.0
        )

    assert event.to_dict()["total"] == 5.0


def test_a_billing_message_reads_as_the_fulfillment_payment_received_class():
    example = load_example("patterns/sharing-event-classes-across-domains/005.py")
    domain = example.fulfillment_domain
    domain.init(traverse=False)
    raw = {
        "data": {"payment_id": "p1", "order_id": "o1", "amount": 20.0},
        "metadata": {
            "headers": {
                "id": "msg-1",
                "type": "Billing.PaymentReceived.v1",
                "time": "2025-01-01T00:00:00+00:00",
                "stream": "billing::payment-p1",
            },
            "envelope": {"specversion": "1.0"},
            "domain": {
                "kind": "EVENT",
                "stream_category": "billing::payment",
                "version": 1,
                "sequence_id": "0",
                "asynchronous": True,
            },
        },
    }

    with domain.domain_context():
        event = Message.deserialize(raw, validate=False).to_domain_object()

    assert isinstance(event, example.PaymentReceived)
    assert (event.payment_id, event.order_id, event.amount) == ("p1", "o1", 20.0)
