"""The examples on ``docs/concepts/async-processing/priority-lanes.md`` behave as the page says."""

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


def _run(example, work):
    """Run ``work``, then a test-mode engine, and return what each stream got."""
    domain = example.domain
    with domain.domain_context():
        work(example)
        priorities = {
            row.data.get("customer_id") or row.data["product_id"]: row.priority
            for row in domain._get_outbox_repo("default").query.all().items
        }
        Engine(domain, test_mode=True).run()
        broker = domain.brokers["default"]
        published = {
            stream: [payload["data"] for _, payload in broker.read(stream, "t", 10)]
            for stream in STREAMS
        }
    return priorities, published


def _update(example, customer_id):
    return example.UpdateCustomer(customer_id=customer_id, loyalty_tier="GOLD")


def test_the_context_manager_sends_migration_events_to_the_backfill_lane():
    example = load_example("concepts/async-processing/priority-lanes/001.py")
    example.domain.init(traverse=False)
    migration_data = [
        {"id": "cust-1", "tier": "GOLD"},
        {"id": "cust-2", "tier": "SILVER"},
    ]

    priorities, published = _run(
        example, lambda ex: ex.backfill_loyalty_tiers(migration_data)
    )

    assert priorities == {"cust-1": Priority.LOW, "cust-2": Priority.LOW}
    assert [e["customer_id"] for e in published["crm::customer:backfill"]] == [
        "cust-1",
        "cust-2",
    ]
    assert published["crm::customer"] == []
    assert current_priority() == Priority.NORMAL


def test_production_traffic_stays_on_the_primary_lane():
    example = load_example("concepts/async-processing/priority-lanes/001.py")
    example.domain.init(traverse=False)

    priorities, published = _run(
        example, lambda ex: ex.domain.process(_update(ex, "cust-9"))
    )

    assert priorities == {"cust-9": Priority.NORMAL}
    assert [e["customer_id"] for e in published["crm::customer"]] == ["cust-9"]
    assert published["crm::customer:backfill"] == []


def test_the_innermost_context_wins():
    example = load_example("concepts/async-processing/priority-lanes/001.py")
    example.domain.init(traverse=False)

    priorities, published = _run(
        example,
        lambda ex: ex.process_nested(
            _update(ex, "cust-1"), _update(ex, "cust-2"), _update(ex, "cust-3")
        ),
    )

    assert priorities == {
        "cust-1": Priority.LOW,
        "cust-2": Priority.CRITICAL,
        "cust-3": Priority.LOW,
    }
    assert [e["customer_id"] for e in published["crm::customer"]] == ["cust-2"]
    assert sorted(e["customer_id"] for e in published["crm::customer:backfill"]) == [
        "cust-1",
        "cust-3",
    ]


def test_the_explicit_parameter_sends_one_command_to_the_backfill_lane():
    example = load_example("concepts/async-processing/priority-lanes/001.py")
    example.domain.init(traverse=False)

    priorities, published = _run(example, lambda ex: ex.reindex_catalog())

    assert priorities == {"SKU-001": Priority.BULK}
    assert [e["product_id"] for e in published["crm::product:backfill"]] == ["SKU-001"]
    assert published["crm::product"] == []


def test_the_explicit_parameter_beats_the_context_manager():
    example = load_example("concepts/async-processing/priority-lanes/001.py")
    example.domain.init(traverse=False)

    priorities, published = _run(
        example, lambda ex: ex.process_urgently(_update(ex, "cust-1"))
    )

    assert priorities == {"cust-1": Priority.CRITICAL}
    assert [e["customer_id"] for e in published["crm::customer"]] == ["cust-1"]
    assert published["crm::customer:backfill"] == []
