"""Run the example on ``docs/reference/adapters/broker/custom-brokers.md``.

The example is the ``delegating_broker`` package. The broker registry stores a
broker by its dotted import path, so the package's folder goes on ``sys.path``
and the test imports it by name.
"""

import sys

import pytest

from tests.docs.support import DOCS_SRC

_PACKAGE_PARENT = str(DOCS_SRC / "adapters" / "broker" / "custom-brokers")
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

import delegating_broker

from protean.adapters.broker.inline import InlineBroker

pytestmark = pytest.mark.no_test_domain


def test_broker_implements_every_abstract_method():
    assert delegating_broker.DelegatingBroker.__abstractmethods__ == frozenset()


def test_domain_uses_the_custom_broker():
    with delegating_broker.domain.domain_context():
        broker = delegating_broker.domain.brokers["default"]

        assert isinstance(broker, delegating_broker.DelegatingBroker)
        assert isinstance(broker._delegate, InlineBroker)


def test_published_message_is_stored_by_the_delegate():
    with delegating_broker.domain.domain_context():
        broker = delegating_broker.domain.brokers["default"]
        broker.publish("invoices", {"invoice_id": "I1"})

        # Read straight from the delegate: the message went through it
        _, message = broker._delegate.get_next("invoices", "billing")
        assert message == {"invoice_id": "I1"}


def test_get_next_on_an_empty_stream_returns_none():
    with delegating_broker.domain.domain_context():
        broker = delegating_broker.domain.brokers["default"]

        assert broker.get_next("empty-stream", "billing") is None
