"""The message-enrichment skill's audit enricher survives the outbox.

An aggregate enricher runs for every aggregate Protean saves, including the
outbox rows written when an aggregate raises an event. The skill, the message
enrichment guide and the audit fields pattern skip an aggregate without the
audit field. These tests show why the check is needed and that it works.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from protean import Domain
from protean.fields import Identifier, String
from protean.utils.globals import g

pytestmark = pytest.mark.no_test_domain


def _domain_with_enricher(guarded: bool):
    domain = Domain(name="EnrichmentClaims")
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
    return domain, Order, stamped


def test_the_enricher_runs_on_outbox_rows():
    domain, Order, stamped = _domain_with_enricher(guarded=True)

    with domain.domain_context(current_user="alice"):
        order = Order(customer_id="c-1")
        order.place()
        domain.repository_for(Order).add(order)

    assert stamped[0] == "Order"
    assert "Outbox" in stamped


def test_an_unguarded_enricher_fails_on_the_outbox_row():
    domain, Order, _ = _domain_with_enricher(guarded=False)

    with domain.domain_context(current_user="alice"):
        order = Order(customer_id="c-1")
        order.place()
        with pytest.raises(ValidationError, match="updated_by"):
            domain.repository_for(Order).add(order)


def test_the_guarded_enricher_stamps_the_aggregate():
    domain, Order, _ = _domain_with_enricher(guarded=True)

    with domain.domain_context(current_user="alice"):
        order = Order(customer_id="c-1")
        order.place()
        domain.repository_for(Order).add(order)
        stored = domain.repository_for(Order).get(order.id)

    assert stored.created_by == "alice"
    assert stored.updated_by == "alice"
