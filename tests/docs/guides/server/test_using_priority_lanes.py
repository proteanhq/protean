"""The examples on the using priority lanes guide behave as the page says."""

import pytest

from protean.server import Engine
from protean.utils.processing import Priority, current_priority
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

STREAMS = (
    "crm::customer",
    "crm::customer:backfill",
    "crm::product",
    "crm::product:backfill",
)


def _published(example, run):
    domain = example.domain
    with domain.domain_context():
        run(example)
        Engine(domain, test_mode=True).run()
        broker = domain.brokers["default"]
        return {
            stream: [payload["data"] for _, payload in broker.read(stream, "t", 10)]
            for stream in STREAMS
        }


def test_low_priority_commands_publish_to_the_backfill_stream():
    example = load_example("guides/server/using-priority-lanes/001.py")
    example.domain.init(traverse=False)

    published = _published(example, lambda ex: ex.backfill_loyalty_tiers())

    assert sorted(e["customer_id"] for e in published["crm::customer:backfill"]) == [
        "cust-1",
        "cust-2",
    ]
    assert published["crm::customer"] == []
    assert current_priority() == Priority.NORMAL


def test_the_explicit_priority_parameter_routes_one_command_to_backfill():
    example = load_example("guides/server/using-priority-lanes/001.py")
    example.domain.init(traverse=False)

    published = _published(example, lambda ex: ex.reindex_catalog())

    assert [e["product_id"] for e in published["crm::product:backfill"]] == ["SKU-001"]
    assert published["crm::product"] == []


def test_normal_priority_commands_stay_on_the_primary_stream():
    example = load_example("guides/server/using-priority-lanes/001.py")
    example.domain.init(traverse=False)

    def update_one(ex):
        ex.domain.process(ex.UpdateCustomer(customer_id="cust-9", loyalty_tier="GOLD"))

    published = _published(example, update_one)

    assert [e["customer_id"] for e in published["crm::customer"]] == ["cust-9"]
    assert published["crm::customer:backfill"] == []


def test_with_lanes_disabled_low_priority_work_stays_on_the_primary_stream():
    example = load_example("guides/server/using-priority-lanes/001.py")
    example.domain.config["server"]["priority_lanes"]["enabled"] = False
    example.domain.init(traverse=False)

    published = _published(example, lambda ex: ex.backfill_loyalty_tiers())

    assert len(published["crm::customer"]) == 2
    assert published["crm::customer:backfill"] == []


@pytest.mark.xfail(
    strict=True,
    reason="With stream subscriptions, the engine reads commands from a broker "
    "stream that asynchronous commands are never published to",
)
def test_asynchronous_commands_also_reach_the_backfill_stream():
    example = load_example("guides/server/using-priority-lanes/001.py")
    example.domain.config["command_processing"] = "async"
    example.domain.init(traverse=False)

    published = _published(example, lambda ex: ex.backfill_loyalty_tiers())

    assert len(published["crm::customer:backfill"]) == 2
