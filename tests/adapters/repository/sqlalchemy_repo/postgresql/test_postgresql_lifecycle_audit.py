from datetime import UTC, datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, String
from protean.utils.globals import g

_SENTINEL = datetime(2000, 1, 1, tzinfo=UTC)


class Ledger(BaseAggregate):
    name: String(max_length=50)
    created_at: DateTime(auto_now_add=True)
    updated_at: DateTime(auto_now=True)
    created_by: String(max_length=50)
    updated_by: String(max_length=50)


@pytest.mark.postgresql
def test_auto_now_and_aggregate_enricher_persist_and_retrieve(test_domain):
    test_domain.register(Ledger)

    @test_domain.aggregate_enricher
    def stamp_audit(aggregate):
        user = g.get("current_user")
        aggregate.updated_by = user
        if aggregate.created_by is None:
            aggregate.created_by = user

    test_domain.init(traverse=False)

    # Create: auto_now/auto_now_add stamped; enricher stamps both audit fields.
    with test_domain.domain_context(current_user="alice"):
        repo = test_domain.repository_for(Ledger)
        ledger = Ledger(name="cash")
        repo.add(ledger)
        ledger_id = ledger.id

        got = repo.get(ledger_id)
        assert got.created_at is not None and got.updated_at is not None
        assert got.created_by == "alice" and got.updated_by == "alice"

    # Update under a different user: auto_now refreshes, auto_now_add is frozen,
    # created_by is preserved and updated_by is refreshed — all round-tripped
    # through the SQL columns.
    with test_domain.domain_context(current_user="bob"):
        repo = test_domain.repository_for(Ledger)
        stored = repo.get(ledger_id)
        stored.created_at = _SENTINEL
        stored.updated_at = _SENTINEL
        stored.name = "petty cash"
        repo.add(stored)

        # The SQL DateTime column stores naive timestamps, so compare by year
        # rather than the tz-aware sentinel: created_at stays at the frozen
        # sentinel year, updated_at advances to the current year.
        got = repo.get(ledger_id)
        assert got.created_at.year == 2000  # auto_now_add frozen on update
        assert got.updated_at.year >= 2026  # auto_now refreshed on update
        assert got.created_by == "alice"
        assert got.updated_by == "bob"
