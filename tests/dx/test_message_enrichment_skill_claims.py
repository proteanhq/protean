"""The message-enrichment skill's audit enricher stamps only the user's aggregates.

An aggregate enricher runs when a repository saves an aggregate to a database,
and never for an event-sourced aggregate. Protean also saves some of its own
records through repositories (outbox rows, the in-memory event store's message
records), and the enricher never runs for those. The skill, the message
enrichment guide and the audit fields pattern skip an aggregate without the
audit field, so the enricher also works in a domain where some aggregates have
no audit fields. These tests check both claims.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from protean import Domain
from protean.fields import Identifier, String
from protean.utils.globals import g

pytestmark = pytest.mark.no_test_domain


def _domain_with_enricher(guarded: bool, outbox: bool = True):
    domain = Domain(name="EnrichmentClaims")
    if outbox:
        domain.config["enable_outbox"] = True
        domain.config["server"]["default_subscription_type"] = "stream"
    stamped: list[str] = []

    @domain.event(part_of="Order")
    class OrderPlaced:
        order_id = Identifier()

    @domain.aggregate
    class Order:
        customer_id = String(required=True)
        created_by = String()
        updated_by = String()

        def place(self):
            self.raise_(OrderPlaced(order_id=self.id))

    @domain.aggregate
    class Tag:
        name = String(required=True)

    @domain.aggregate_enricher
    def stamp_audit(aggregate):
        stamped.append(type(aggregate).__name__)
        if guarded and not hasattr(aggregate, "updated_by"):
            return
        user = g.get("current_user")
        aggregate.updated_by = user
        if aggregate.created_by is None:
            aggregate.created_by = user

    domain.init(traverse=False)
    return domain, Order, Tag, stamped


@pytest.mark.parametrize("outbox", [True, False], ids=["outbox", "no-outbox"])
def test_the_enricher_never_runs_on_framework_records(outbox):
    domain, Order, _, stamped = _domain_with_enricher(guarded=False, outbox=outbox)

    with domain.domain_context(current_user="alice"):
        order = Order(customer_id="c-1")
        order.place()
        domain.repository_for(Order).add(order)

    assert stamped == ["Order"]


def test_the_guarded_enricher_stamps_the_aggregate():
    domain, Order, _, _ = _domain_with_enricher(guarded=True)

    with domain.domain_context(current_user="alice"):
        order = Order(customer_id="c-1")
        order.place()
        domain.repository_for(Order).add(order)
        stored = domain.repository_for(Order).get(order.id)

    assert stored.created_by == "alice"
    assert stored.updated_by == "alice"


def test_the_guard_skips_an_aggregate_without_audit_fields():
    domain, _, Tag, _ = _domain_with_enricher(guarded=True)

    with domain.domain_context(current_user="alice"):
        tag = Tag(name="urgent")
        domain.repository_for(Tag).add(tag)

        assert domain.repository_for(Tag).get(tag.id).name == "urgent"


def test_an_unguarded_enricher_fails_on_an_aggregate_without_audit_fields():
    domain, _, Tag, _ = _domain_with_enricher(guarded=False)

    with domain.domain_context(current_user="alice"):
        with pytest.raises(ValidationError, match="updated_by"):
            domain.repository_for(Tag).add(Tag(name="urgent"))
