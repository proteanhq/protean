"""The examples on ``docs/concepts/async-processing/engine.md`` behave as the page says."""

import pytest

from protean.server import Engine
from protean.server.engine import CommandDispatcher
from protean.server.subscription.event_store_subscription import (
    EventStoreSubscription,
)
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _place_order(example, order_id: str, **context) -> None:
    domain = example.domain
    with domain.domain_context(**context):
        order = example.Order(order_id=order_id, total=25.0)
        order.raise_(example.OrderPlaced(order_id=order_id, total=25.0))
        domain.repository_for(example.Order).add(order)


def test_the_engine_registers_a_subscription_for_each_event_handler():
    example = load_example("concepts/async-processing/engine/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        engine = example.create_engine(example.domain)
        try:
            assert engine.test_mode is False
            assert {"OrderEventHandler", "TenantAuditHandler"} <= {
                name.rsplit(".", 1)[-1] for name in engine.subscriptions
            }
        finally:
            engine.loop.close()


def test_the_test_engine_runs_the_handler_and_exits():
    example = load_example("concepts/async-processing/engine/001.py")
    example.domain.init(traverse=False)
    _place_order(example, "order-1")

    assert example.placed_orders == []

    with example.domain.domain_context():
        engine = example.create_test_engine(example.domain)
        assert engine.test_mode is True
        engine.run()

    assert example.placed_orders == ["order-1"]


def test_the_engine_infers_the_stream_category_from_the_aggregate():
    example = load_example("concepts/async-processing/engine/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        engine = example.create_engine(example.domain)
        try:
            stream_category, subscription = example.register_order_handler(engine)
        finally:
            engine.loop.close()

    assert stream_category == "shop::order"
    assert isinstance(subscription, EventStoreSubscription)
    assert subscription.handler is example.OrderEventHandler
    assert subscription.stream_category == "shop::order"


def test_command_handlers_of_one_aggregate_share_one_dispatching_subscription():
    example = load_example("concepts/async-processing/engine/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        engine = Engine(example.domain)
        try:
            assert list(engine.subscriptions) == ["commands:identity::user:command"]
            dispatcher = engine.subscriptions["commands:identity::user:command"].handler
            assert isinstance(dispatcher, CommandDispatcher)
        finally:
            engine.loop.close()


def test_the_dispatcher_routes_each_command_to_its_own_handler():
    example = load_example("concepts/async-processing/engine/002.py")
    domain = example.domain
    domain.init(traverse=False)

    with domain.domain_context():
        domain.process(example.RegisterUser(user_id="u1", email="ada@example.com"))
        domain.process(example.RegisterUser(user_id="u2", email="bob@example.com"))
        domain.process(example.DeactivateUser(user_id="u1"))
        Engine(domain, test_mode=True).run()

        repo = domain.repository_for(example.User)
        assert repo.get("u1").active is False
        assert repo.get("u2").active is True


def test_the_subscriber_receives_payloads_from_its_broker_stream():
    example = load_example("concepts/async-processing/engine/003.py")
    domain = example.domain
    domain.init(traverse=False)

    with domain.domain_context():
        broker = domain.brokers["default"]
        broker.publish("external_events", {"type": "OrderCreated", "id": "o1"})
        broker.publish("other_events", {"type": "OrderCreated", "id": "o2"})
        Engine(domain, test_mode=True).run()

    assert example.received == [{"type": "OrderCreated", "id": "o1"}]


def test_handlers_see_the_context_of_the_request_that_raised_the_event():
    example = load_example("concepts/async-processing/engine/001.py")
    example.domain.init(traverse=False)
    _place_order(example, "order-1", tenant_id="acme")
    _place_order(example, "order-2", tenant_id="globex")

    with example.domain.domain_context():
        Engine(example.domain, test_mode=True).run()

    assert sorted(example.seen_tenants) == [
        ("acme", "acme"),
        ("globex", "globex"),
    ]
