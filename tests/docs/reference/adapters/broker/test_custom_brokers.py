"""Run the example on ``docs/reference/adapters/broker/custom-brokers.md``.

The example is the ``delegating_broker`` package. The broker registry stores a
broker by its dotted import path, so the package's folder goes on ``sys.path``
and the test imports it by name.
"""

import re
import sys

import pytest

from tests.docs.support import DOCS, DOCS_SRC

_PACKAGE_PARENT = str(DOCS_SRC / "adapters" / "broker" / "custom-brokers")
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

import delegating_broker

from protean.adapters.broker.inline import InlineBroker
from protean.infra.broker import Broker
from protean.port.broker import BrokerPort, DeadLetterQueuePort

pytestmark = pytest.mark.no_test_domain


def test_page_lists_every_abstract_method():
    page = (DOCS / "reference/adapters/broker/custom-brokers.md").read_text()
    section = page.split("## Architecture")[1].split("A broker that does not")[0]
    # The prose around the list names flags and fallbacks, so read the bullets only.
    bullets = [line for line in section.splitlines() if line.startswith("- ")]
    listed = set(re.findall(r"`(\w+)`", "\n".join(bullets)))

    assert (
        listed
        == BrokerPort.__abstractmethods__ | DeadLetterQueuePort.__abstractmethods__
    )


def test_example_reads_back_and_acknowledges_the_message():
    assert delegating_broker.message == {"order_id": "1"}
    assert delegating_broker.acknowledged is True


def test_second_ack_of_the_same_message_fails():
    with delegating_broker.domain.domain_context():
        broker = delegating_broker.domain.brokers["default"]

        assert (
            broker.ack("orders", delegating_broker.identifier, "order-processor")
            is False
        )


def test_domain_uses_the_custom_broker():
    with delegating_broker.domain.domain_context():
        broker = delegating_broker.domain.brokers["default"]

        assert isinstance(broker, Broker)
        assert isinstance(broker._adapter, delegating_broker.DelegatingBroker)
        assert isinstance(broker._adapter._delegate, InlineBroker)


def test_published_message_is_stored_by_the_delegate():
    with delegating_broker.domain.domain_context():
        broker = delegating_broker.domain.brokers["default"]
        broker.publish("invoices", {"invoice_id": "I1"})

        # Read straight from the delegate: the message went through it
        messages = broker._adapter._delegate.read("invoices", "billing", 1)
        assert [message for _, message in messages] == [{"invoice_id": "I1"}]


def test_get_next_on_an_empty_stream_returns_none():
    with delegating_broker.domain.domain_context():
        broker = delegating_broker.domain.brokers["default"]

        assert broker.get_next("empty-stream", "billing") is None


def test_broker_subclasses_only_the_port():
    assert delegating_broker.DelegatingBroker.__bases__ == (DeadLetterQueuePort,)
    assert BrokerPort in DeadLetterQueuePort.__mro__


def test_broker_stores_its_name_domain_and_config():
    with delegating_broker.domain.domain_context():
        adapter = delegating_broker.domain.brokers["default"]._adapter

        assert adapter.name == "default"
        assert adapter.domain is delegating_broker.domain
        assert adapter.config["provider"] == "delegating_inline"
