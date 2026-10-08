"""The examples on the subscribers guide behave as the page says."""

import asyncio
import logging

import pytest

from protean import Domain
from protean.exceptions import ConfigurationError
from protean.server import Engine
from protean.utils.query import Q
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def test_payment_subscriber_confirms_the_payment_on_publish():
    example = load_example("guides/consume-state/003.py")

    with example.domain.domain_context():
        payment = example.Payment(order_id="order-123", amount=49.99)
        example.domain.repository_for(example.Payment).add(payment)

        example.domain.brokers["default"].publish(
            "payment_gateway",
            {"order_id": "order-123", "transaction_id": "txn-789"},
        )

        updated = example.domain.repository_for(example.Payment).get(payment.id)

    assert updated.status == "CONFIRMED"


def test_webhook_subscribers_mark_the_order_paid_then_shipped():
    example = load_example("guides/consume-state/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.Order)
        order = example.Order(customer_email="alice@example.com", total_amount=149.99)
        repo.add(order)

        example.domain.brokers["default"].publish(
            "payment_gateway",
            {
                "order_id": str(order.id),
                "status": "SUCCESS",
                "transaction_id": "txn-42",
            },
        )
        assert repo.get(order.id).status == "PAID"

        example.domain.brokers["default"].publish(
            "shipping_updates",
            {"order_id": str(order.id), "tracking_number": "TRACK-12345"},
        )
        assert repo.get(order.id).status == "SHIPPED"


def test_payment_webhook_ignores_a_status_other_than_success():
    example = load_example("guides/consume-state/004.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        repo = example.domain.repository_for(example.Order)
        order = example.Order(customer_email="alice@example.com", total_amount=149.99)
        repo.add(order)

        example.PaymentWebhookSubscriber()(
            {"order_id": str(order.id), "status": "DECLINED"}
        )

        assert repo.get(order.id).status == "PENDING"


def test_payment_webhook_handle_error_logs_the_order_id(caplog):
    example = load_example("guides/consume-state/004.py")

    with caplog.at_level(logging.ERROR):
        example.PaymentWebhookSubscriber.handle_error(
            KeyError("status"), {"order_id": "order-9"}
        )

    assert "Failed to process payment for order order-9" in caplog.text


def test_subscribers_listen_on_their_streams_and_brokers():
    example = load_example("guides/consume-state/subscribers/001.py")
    example.domain.init(traverse=False)

    assert example.ExternalOrderSubscriber.meta_.stream == "external_orders"
    assert example.ExternalOrderSubscriber.meta_.broker == "default"
    assert example.OrderSubscriber.meta_.stream == "order_events"
    assert example.OrderSubscriber.meta_.broker == "default"
    assert example.AnalyticsSubscriber.meta_.stream == "analytics_events"
    assert example.AnalyticsSubscriber.meta_.broker == "analytics"
    assert set(example.domain.brokers) == {"default", "analytics"}


def test_a_subscriber_on_an_unconfigured_broker_fails_init():
    example = load_example("guides/consume-state/subscribers/001.py")
    domain = Domain(name="NoAnalytics")
    domain.register(
        example.AnalyticsSubscriber, stream="analytics_events", broker="analytics"
    )

    with pytest.raises(ConfigurationError, match="Broker `analytics`"):
        domain.init(traverse=False)


def test_handle_error_logs_the_failure(caplog):
    example = load_example("guides/consume-state/subscribers/002.py")
    example.domain.init(traverse=False)

    with caplog.at_level(logging.ERROR):
        example.PaymentSubscriber.handle_error(
            ValueError("card declined"), {"order_id": "order-1"}
        )

    assert "Failed to process payment message: card declined" in caplog.text


def test_the_engine_calls_handle_error_when_the_subscriber_raises(caplog):
    example = load_example("guides/consume-state/subscribers/002.py")

    @example.domain.subscriber(stream="payment_gateway")
    class DecliningPaymentSubscriber(example.PaymentSubscriber):
        def __call__(self, payload: dict) -> None:
            raise ValueError("card declined")

    example.domain.init(traverse=False)
    engine = Engine(domain=example.domain, test_mode=True)

    with caplog.at_level(logging.ERROR):
        handled = asyncio.run(
            engine.handle_broker_message(
                DecliningPaymentSubscriber,
                {"order_id": "order-1"},
                message_id="msg-1",
                stream="payment_gateway",
            )
        )

    assert handled is False
    assert "Failed to process payment message: card declined" in caplog.text


def test_the_engine_survives_a_failing_handle_error(caplog):
    example = load_example("guides/consume-state/subscribers/002.py")

    @example.domain.subscriber(stream="payment_gateway")
    class BrokenRecoverySubscriber(example.PaymentSubscriber):
        def __call__(self, payload: dict) -> None:
            raise ValueError("card declined")

        @classmethod
        def handle_error(cls, exc: Exception, message: dict) -> None:
            raise RuntimeError("recovery store is down")

    example.domain.init(traverse=False)
    engine = Engine(domain=example.domain, test_mode=True)

    with caplog.at_level(logging.ERROR):
        handled = asyncio.run(
            engine.handle_broker_message(
                BrokenRecoverySubscriber,
                {"order_id": "order-1"},
                message_id="msg-2",
                stream="payment_gateway",
            )
        )

    assert handled is False
    assert "recovery store is down" in caplog.text


def test_valid_payload_issues_record_payment():
    example = load_example("guides/consume-state/subscribers/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.PaymentWebhookSubscriber()(
            {"order_id": "order-7", "status": "PAID", "amount": 25.5}
        )
        payment = example.domain.repository_for(example.Payment).find_by(
            order_id="order-7"
        )

    assert payment.status == "PAID"
    assert payment.amount == 25.5


@pytest.mark.parametrize(
    "payload, warning",
    [
        ({"order_id": "order-7", "status": "PAID"}, "Missing fields ['amount']"),
        (
            {"order_id": "order-7", "status": "PAID", "amount": "25.5"},
            "Invalid amount type: <class 'str'>",
        ),
    ],
)
def test_invalid_payload_is_skipped_with_a_warning(payload, warning, caplog):
    example = load_example("guides/consume-state/subscribers/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context(), caplog.at_level(logging.WARNING):
        example.PaymentWebhookSubscriber()(payload)
        recorded = example.domain.repository_for(example.Payment).find(
            Q(order_id="order-7")
        )

    assert warning in caplog.text
    assert recorded.total == 0


def test_message_context_gives_the_broker_message_id_for_idempotency():
    example = load_example("guides/consume-state/subscribers/004.py")
    example.domain.init(traverse=False)
    engine = Engine(domain=example.domain, test_mode=True)
    payload = {"order_id": "order-5", "items": ["book", "pen"]}

    for _ in range(2):
        handled = asyncio.run(
            engine.handle_broker_message(
                example.OrderSubscriber, payload, message_id="msg-1", stream="orders"
            )
        )
        assert handled is True

    with example.domain.domain_context():
        shipments = example.domain.repository_for(example.Shipment).find(
            Q(order_id="order-5")
        )
        processed = example.domain.repository_for(example.ProcessedMessage).find(
            Q(message_id="msg-1")
        )

    assert shipments.total == 1
    assert shipments.items[0].items == ["book", "pen"]
    assert processed.total == 1


def test_a_long_message_id_is_recorded_and_deduplicated():
    example = load_example("guides/consume-state/subscribers/004.py")
    example.domain.init(traverse=False)
    engine = Engine(domain=example.domain, test_mode=True)
    message_id = "fulfillment::international_shipment_request-" + "x" * 200 + "-1"

    for _ in range(2):
        handled = asyncio.run(
            engine.handle_broker_message(
                example.OrderSubscriber,
                {"order_id": "order-6", "items": ["lamp"]},
                message_id=message_id,
                stream="orders",
            )
        )
        assert handled is True

    with example.domain.domain_context():
        shipments = example.domain.repository_for(example.Shipment).find(
            Q(order_id="order-6")
        )

    assert shipments.total == 1
