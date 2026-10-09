"""The examples on the external event dispatch guide behave as the page says."""

import logging

import pytest

from protean.server import Engine
from protean.utils.outbox import OutboxStatus
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

STREAM = "myapp::order"


def _outbox_rows(example) -> list[tuple[str, str, str]]:
    with example.domain.domain_context():
        rows = example.domain._get_outbox_repo("default").query.all().items
    return sorted((row.type, row.target_broker, row.status) for row in rows)


def test_a_published_event_gets_one_outbox_row_per_broker():
    example = load_example("guides/server/external-event-dispatch/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.ship_order("1Z999AA10123456784")
        example.pack_order()

    pending = OutboxStatus.PENDING.value
    assert _outbox_rows(example) == [
        ("MyApp.OrderPacked.v1", "default", pending),
        ("MyApp.OrderShipped.v1", "default", pending),
        ("MyApp.OrderShipped.v1", "partner_events", pending),
    ]


def test_the_engine_publishes_the_stripped_envelope_to_the_external_broker():
    example = load_example("guides/server/external-event-dispatch/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        order = example.ship_order("1Z999AA10123456784")
        example.pack_order()

    Engine(example.domain, test_mode=True).run()

    assert {status for _, _, status in _outbox_rows(example)} == {
        OutboxStatus.PUBLISHED.value
    }
    with example.domain.domain_context():
        external = example.domain.brokers["partner_events"].read(STREAM, "probe", 10)
        internal = example.domain.brokers["default"].read(STREAM, "probe", 10)

    # Only the published event leaves the bounded context.
    assert len(external) == 1
    _, message = external[0]
    assert message["data"]["order_id"] == order.id
    assert message["data"]["tracking_number"] == "1Z999AA10123456784"
    assert message["metadata"]["headers"]["type"] == "MyApp.OrderShipped.v1"
    for internal_field in ("expected_version", "asynchronous", "priority"):
        assert internal_field not in message["metadata"]["domain"]
    assert "event_store" not in message["metadata"]
    assert message["metadata"]["envelope"] == {"specversion": "1.0"}

    # The internal broker still gets both events, with the full metadata.
    assert sorted(m["metadata"]["headers"]["type"] for _, m in internal) == [
        "MyApp.OrderPacked.v1",
        "MyApp.OrderShipped.v1",
    ]
    assert all("priority" in m["metadata"]["domain"] for _, m in internal)


def test_published_events_without_external_brokers_log_a_warning(caplog):
    example = load_example("guides/server/external-event-dispatch/001.py")
    example.domain.config["outbox"]["external_brokers"] = []

    with caplog.at_level(logging.WARNING):
        example.domain.init(traverse=False)

    assert (
        "Domain has published events but no external_brokers configured in outbox "
        "settings. Published events will only be dispatched internally."
    ) in caplog.messages


def test_configured_external_brokers_do_not_warn(caplog):
    example = load_example("guides/server/external-event-dispatch/001.py")

    with caplog.at_level(logging.WARNING):
        example.domain.init(traverse=False)

    assert not [m for m in caplog.messages if "no external_brokers" in m]
