"""The examples on the correlation and causation guide behave as the page says."""

import logging
import re

import pytest
import structlog

from protean.integrations.logging import ProteanCorrelationFilter
from protean.server import Engine
from protean.utils.globals import g
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

ITEMS = [{"sku": "BOOK-1", "qty": 2}]


def _shipping_domain():
    example = load_example("guides/observability/correlation-and-causation/001.py")
    example.domain.init(traverse=False)
    return example


def _chain_messages(domain, correlation_id):
    """Return the stored commands and events of one chain, keyed by type."""
    messages = [
        m
        for m in domain.event_store.store.read("$all")
        if m.metadata.domain.correlation_id == correlation_id
    ]
    return {m.metadata.headers.type: m for m in messages}


def test_place_order_gives_every_message_one_generated_correlation_id():
    example = _shipping_domain()

    with example.domain.domain_context():
        example.place_order(ITEMS)
        Engine(example.domain, test_mode=True).run()

        messages = [
            m
            for m in example.domain.event_store.store.read("$all")
            if m.metadata.domain.kind in ("COMMAND", "EVENT")
        ]

    assert len(messages) == 4
    correlation_ids = {m.metadata.domain.correlation_id for m in messages}
    assert len(correlation_ids) == 1
    (correlation_id,) = correlation_ids
    assert re.fullmatch(r"[0-9a-f]{32}", correlation_id)


def test_explicit_correlation_id_flows_through_the_whole_chain():
    example = _shipping_domain()

    with example.domain.domain_context():
        example.place_order_from_gateway(ITEMS)
        Engine(example.domain, test_mode=True).run()

        by_type = _chain_messages(example.domain, "req-abc-123-from-gateway")

    assert sorted(by_type) == [
        "Shipping.ConfirmOrder.v1",
        "Shipping.OrderConfirmed.v1",
        "Shipping.OrderPlaced.v1",
        "Shipping.PlaceOrder.v1",
    ]


def test_each_causation_id_points_at_the_immediate_parent():
    example = _shipping_domain()

    with example.domain.domain_context():
        example.domain.process(
            example.PlaceOrder(customer_id="cust-123", items=ITEMS),
            correlation_id="ext-123",
        )
        Engine(example.domain, test_mode=True).run()

        by_type = _chain_messages(example.domain, "ext-123")

    place = by_type["Shipping.PlaceOrder.v1"]
    placed = by_type["Shipping.OrderPlaced.v1"]
    confirm = by_type["Shipping.ConfirmOrder.v1"]
    confirmed = by_type["Shipping.OrderConfirmed.v1"]

    assert place.metadata.domain.causation_id is None
    assert placed.metadata.domain.causation_id == place.metadata.headers.id
    assert confirm.metadata.domain.causation_id == placed.metadata.headers.id
    assert confirmed.metadata.domain.causation_id == confirm.metadata.headers.id


def _trace_ids_for(example, message_type):
    with example.domain.domain_context():
        example.domain.process(
            example.PlaceOrder(customer_id="cust-123", items=ITEMS),
            correlation_id="ext-123",
        )
        Engine(example.domain, test_mode=True).run()

        by_type = _chain_messages(example.domain, "ext-123")
        message = by_type[message_type]
        domain_object = message.to_domain_object()

        return by_type, example.trace_ids(domain_object, message)


def test_trace_ids_reads_the_ids_from_a_command_and_from_a_message():
    example = _shipping_domain()

    by_type, (object_ids, message_ids) = _trace_ids_for(
        example, "Shipping.ConfirmOrder.v1"
    )

    placed_id = by_type["Shipping.OrderPlaced.v1"].metadata.headers.id
    assert object_ids == ("ext-123", placed_id)
    assert message_ids == ("ext-123", placed_id)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BaseEvent._build_metadata ignores the correlation_id and causation_id "
        "in the metadata it is given, so an event rebuilt from a stored "
        "message loses both IDs"
    ),
)
def test_trace_ids_reads_the_ids_from_an_event():
    example = _shipping_domain()

    by_type, (object_ids, message_ids) = _trace_ids_for(
        example, "Shipping.OrderPlaced.v1"
    )

    place_id = by_type["Shipping.PlaceOrder.v1"].metadata.headers.id
    assert message_ids == ("ext-123", place_id)
    assert object_ids == ("ext-123", place_id)


def test_traverse_walks_up_down_and_builds_the_tree():
    example = _shipping_domain()

    with example.domain.domain_context():
        example.domain.process(
            example.PlaceOrder(customer_id="cust-123", items=ITEMS),
            correlation_id="ext-123",
        )
        Engine(example.domain, test_mode=True).run()

        by_type = _chain_messages(example.domain, "ext-123")
        chain, effects, root = example.traverse(
            by_type["Shipping.OrderConfirmed.v1"],
            by_type["Shipping.PlaceOrder.v1"],
        )

    assert [m.metadata.headers.type for m in chain] == [
        "Shipping.PlaceOrder.v1",
        "Shipping.OrderPlaced.v1",
        "Shipping.ConfirmOrder.v1",
        "Shipping.OrderConfirmed.v1",
    ]
    assert [m.metadata.headers.type for m in effects] == [
        "Shipping.OrderPlaced.v1",
        "Shipping.ConfirmOrder.v1",
        "Shipping.OrderConfirmed.v1",
    ]
    assert root.message_type == "Shipping.PlaceOrder.v1"
    assert [child.message_type for child in root.children] == [
        "Shipping.OrderPlaced.v1"
    ]


def test_print_chain_prints_each_message_in_causal_order(capsys):
    example = _shipping_domain()

    with example.domain.domain_context():
        example.domain.process(
            example.PlaceOrder(customer_id="cust-123", items=ITEMS),
            correlation_id="ext-123",
        )
        Engine(example.domain, test_mode=True).run()
        capsys.readouterr()

        example.print_chain()

    assert capsys.readouterr().out.splitlines() == [
        "COMMAND: Shipping.PlaceOrder.v1",
        "EVENT: Shipping.OrderPlaced.v1",
        "COMMAND: Shipping.ConfirmOrder.v1",
        "EVENT: Shipping.OrderConfirmed.v1",
    ]


def test_correlation_trace_is_empty_for_an_unknown_correlation_id():
    example = _shipping_domain()

    with example.domain.domain_context():
        assert example.domain.correlation_trace("ext-123") == []


def test_check_order_chain_passes_for_the_full_chain():
    example = _shipping_domain()

    with example.domain.domain_context():
        example.place_order_from_gateway(ITEMS)
        Engine(example.domain, test_mode=True).run()

        example.check_order_chain("req-abc-123-from-gateway")

        with pytest.raises(AssertionError):
            example.check_order_chain("no-such-correlation-id")


@pytest.mark.fastapi
def test_middleware_uses_the_correlation_id_header_for_the_command():
    from fastapi.testclient import TestClient

    example = load_example("guides/observability/correlation-and-causation/002.py")

    with TestClient(example.app) as client:
        response = client.post(
            "/orders",
            json={"customer_id": "cust-123", "items": ITEMS},
            headers={"X-Correlation-ID": "ext-123"},
        )

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "ext-123"

    with example.domain.domain_context():
        chain = example.domain.correlation_trace("ext-123")

    assert [node.message_type for node in chain] == ["Shipping.PlaceOrder.v1"]


@pytest.mark.fastapi
def test_middleware_falls_back_to_a_generated_correlation_id():
    from fastapi.testclient import TestClient

    example = load_example("guides/observability/correlation-and-causation/002.py")

    with TestClient(example.app) as client:
        response = client.post(
            "/orders", json={"customer_id": "cust-123", "items": ITEMS}
        )

    correlation_id = response.headers["X-Correlation-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", correlation_id)
    with example.domain.domain_context():
        chain = example.domain.correlation_trace(correlation_id)
    assert [node.message_type for node in chain] == ["Shipping.PlaceOrder.v1"]


def _published_commands(domain):
    return {
        m.metadata.headers.type: m
        for m in domain.event_store.store.read("$all")
        if m.metadata.domain.kind == "COMMAND"
    }


def test_payment_subscriber_command_carries_the_source_correlation_id():
    example = load_example("guides/observability/correlation-and-causation/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.domain.brokers["default"].publish(
            "payments",
            {
                "order_id": "order-1",
                "metadata": {"domain": {"correlation_id": "pay-777"}},
            },
        )
        Engine(example.domain, test_mode=True).run()

        commands = _published_commands(example.domain)

    confirm = commands["Payments.ConfirmPayment.v1"]
    assert confirm.metadata.domain.correlation_id == "pay-777"


def test_payment_subscriber_starts_a_fresh_chain_without_a_source_id():
    example = load_example("guides/observability/correlation-and-causation/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.domain.brokers["default"].publish("payments", {"order_id": "order-1"})
        Engine(example.domain, test_mode=True).run()

        commands = _published_commands(example.domain)

    correlation_id = commands[
        "Payments.ConfirmPayment.v1"
    ].metadata.domain.correlation_id
    assert re.fullmatch(r"[0-9a-f]{32}", correlation_id)


def test_fulfillment_subscriber_commands_share_the_source_correlation_id():
    example = load_example("guides/observability/correlation-and-causation/003.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.domain.brokers["default"].publish(
            "fulfillment",
            {
                "order_id": "order-1",
                "metadata": {"domain": {"correlation_id": "ship-42"}},
            },
        )
        Engine(example.domain, test_mode=True).run()

        commands = _published_commands(example.domain)

    assert sorted(commands) == [
        "Payments.NotifyWarehouse.v1",
        "Payments.ReserveInventory.v1",
    ]
    assert {c.metadata.domain.correlation_id for c in commands.values()} == {"ship-42"}


def test_filter_goes_on_every_root_handler():
    root = logging.getLogger()
    handlers = [logging.StreamHandler(), logging.StreamHandler()]
    root.handlers = handlers

    load_example("guides/server/logging/005.py")

    for handler in handlers:
        assert any(isinstance(f, ProteanCorrelationFilter) for f in handler.filters)


def test_filter_tags_a_record_from_a_child_logger():
    example = load_example("guides/observability/correlation-and-causation/001.py")
    example.domain.init(traverse=False)

    root = logging.getLogger()
    records = []

    class Collect(logging.Handler):
        def emit(self, record):
            records.append(record)

    root.handlers = [Collect()]
    load_example("guides/server/logging/005.py")

    with example.domain.domain_context():
        g.correlation_id = "job-9"
        logging.getLogger("myapp.orders").warning("order synced")

    assert len(records) == 1
    assert records[0].correlation_id == "job-9"
    assert records[0].causation_id == ""


def test_structlog_processor_adds_both_ids():
    example = load_example("guides/observability/correlation-and-causation/004.py")
    example.domain.init(traverse=False)

    processors = structlog.get_config()["processors"]
    assert len(processors) == 2
    processor = processors[0]

    with example.domain.domain_context():
        g.correlation_id = "job-9"
        event_dict = processor(None, "info", {"event": "order_synced"})

    assert event_dict["correlation_id"] == "job-9"
    assert event_dict["causation_id"] == ""


def test_structlog_processor_leaves_both_ids_empty_without_a_context():
    load_example("guides/observability/correlation-and-causation/004.py")

    processor = structlog.get_config()["processors"][0]
    event_dict = processor(None, "info", {"event": "startup"})

    assert event_dict["correlation_id"] == ""
    assert event_dict["causation_id"] == ""
