"""Run the examples on ``docs/reference/adapters/broker/inline.md``."""

import pytest

from protean.integrations.pytest import DomainFixture
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_subscriber_is_called_on_publish():
    example = load_example("adapters/broker/inline/001.py")

    assert example.created == ["123"]


def test_each_consumer_group_receives_every_message():
    example = load_example("adapters/broker/inline/001.py")

    expected = {"type": "order.created", "order_id": "A1"}
    assert example.billing_message == expected
    assert example.shipping_message == expected


def test_a_group_gets_each_message_once():
    example = load_example("adapters/broker/inline/001.py")

    with example.domain.domain_context():
        broker = example.domain.brokers["default"]
        broker.publish("invoices", {"invoice_id": "I1"})

        identifier, message = broker.get_next("invoices", "billing")
        assert message == {"invoice_id": "I1"}
        # Not acknowledged yet, and still not handed out a second time
        assert broker.get_next("invoices", "billing") is None
        assert broker.ack("invoices", identifier, "billing") is True


def test_domain_fixture_example_processes_the_message():
    example = load_example("adapters/broker/inline/002.py")

    fixture = DomainFixture(example.domain)
    fixture.setup()
    try:
        with fixture.domain_context():
            example.test_message_processing()
    finally:
        fixture.teardown()

    assert example.processed == [{"type": "test.event", "data": "test"}]
