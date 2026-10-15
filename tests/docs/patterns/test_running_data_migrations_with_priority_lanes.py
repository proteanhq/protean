"""Run the examples on ``docs/patterns/running-data-migrations-with-priority-lanes.md``."""

import pytest

from protean.server import Engine
from protean.utils.processing import Priority, current_priority
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

PRIMARY = "identity::customer"
BACKFILL = "identity::customer:backfill"


@pytest.fixture
def example():
    module = load_example("patterns/running-data-migrations-with-priority-lanes/001.py")
    with module.domain.domain_context():
        yield module


def _add_customers(example, spends):
    repo = example.domain.repository_for(example.Customer)
    for index, spend in enumerate(spends):
        repo.add(example.Customer(name=f"c{index}", lifetime_spend=spend))


def _published(example):
    Engine(example.domain, test_mode=True).run()
    broker = example.domain.brokers["default"]
    return {
        stream: [payload["data"] for _, payload in broker.read(stream, "t", 1000)]
        for stream in (PRIMARY, BACKFILL)
    }


@pytest.mark.parametrize(
    ("spend", "tier"),
    [(12000, "platinum"), (5000, "gold"), (4999.99, "silver"), (0, "bronze")],
)
def test_determine_tier_uses_the_highest_threshold_reached(example, spend, tier):
    assert example.determine_tier(spend) == tier


def test_migration_events_go_to_the_backfill_stream(example):
    _add_customers(example, [12000, 300])

    example.run_migration()

    published = _published(example)
    assert sorted(e["loyalty_tier"] for e in published[BACKFILL]) == [
        "bronze",
        "platinum",
    ]
    assert published[PRIMARY] == []
    assert current_priority() == Priority.NORMAL


def test_a_production_command_stays_on_the_primary_stream(example):
    _add_customers(example, [1500])
    (customer,) = example.domain.repository_for(example.Customer).query.all().items

    example.domain.process(
        example.UpdateCustomerTier(customer_id=customer.id, loyalty_tier="silver")
    )

    published = _published(example)
    assert [e["customer_id"] for e in published[PRIMARY]] == [customer.id]
    assert published[BACKFILL] == []


def test_migration_reaches_every_customer_past_the_default_query_limit(example):
    _add_customers(example, [1000] * 120)

    example.run_migration(batch_size=50)

    tiers = [
        c.loyalty_tier
        for c in example.domain.repository_for(example.Customer)
        .query.limit(None)
        .all()
        .items
    ]
    assert len(tiers) == 120
    assert set(tiers) == {"silver"}


def test_dry_run_changes_nothing(example):
    _add_customers(example, [12000])

    example.run_migration(dry_run=True)

    (customer,) = example.domain.repository_for(example.Customer).query.all().items
    assert customer.loyalty_tier is None
    assert _published(example) == {PRIMARY: [], BACKFILL: []}
