"""Aggregate enrichers run only on aggregates the user registered.

The framework stores its own rows (the memory event store's messages, outbox
rows, processed-message markers) through aggregates too. An audit enricher
that sets a field such as ``updated_by`` must not see those rows, or the save
fails because they have no such field.
"""

import pytest

from protean import Domain
from protean.adapters.event_store.memory import MemoryMessage
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.fields import Identifier, String


class Order(BaseAggregate):
    name: String()
    updated_by: String()

    def place(self) -> None:
        self.raise_(Placed(order_id=self.id))


class Placed(BaseEvent):
    order_id: Identifier()


class Unregistered(BaseAggregate):
    name: String()


def _domain(*, outbox: bool = False) -> tuple[Domain, list[str]]:
    domain = Domain(name="EnricherScope")
    if outbox:
        domain.config["enable_outbox"] = True
        domain.config["server"]["default_subscription_type"] = "stream"
    domain.register(Order)
    domain.register(Placed, part_of=Order)

    seen: list[str] = []

    @domain.aggregate_enricher
    def stamp_audit(aggregate):
        seen.append(type(aggregate).__name__)
        aggregate.updated_by = "alice"

    domain.init(traverse=False)
    return domain, seen


@pytest.mark.no_test_domain
class TestEnricherSkipsInternalAggregates:
    def test_event_store_rows_are_not_enriched(self):
        domain, seen = _domain()
        with domain.domain_context():
            order = Order(name="x")
            order.place()
            domain.repository_for(Order).add(order)

            assert domain.repository_for(Order).get(order.id).updated_by == "alice"
            assert (
                len(
                    domain.event_store.store.read(
                        f"{Order.meta_.stream_category}-{order.id}"
                    )
                )
                == 1
            )
        assert seen == ["Order"]

    def test_outbox_rows_are_not_enriched(self):
        domain, seen = _domain(outbox=True)
        with domain.domain_context():
            order = Order(name="x")
            order.place()
            domain.repository_for(Order).add(order)

            outbox = domain._get_outbox_repo("default")._dao.query.all()
            assert outbox.total == 1
        assert set(seen) == {"Order"}

    def test_processed_message_markers_are_not_enriched(self):
        domain, seen = _domain()
        with domain.domain_context():
            repo = domain._get_processed_message_repo("default")
            repo.mark("message-1", "handler")

            assert repo.is_processed("message-1", "handler")
        assert seen == []


@pytest.mark.no_test_domain
class TestRegistryIsInternal:
    def test_framework_aggregate_is_internal(self):
        domain, _ = _domain()
        assert domain._domain_registry.is_internal(MemoryMessage)

    def test_user_aggregate_is_not_internal(self):
        domain, _ = _domain()
        assert not domain._domain_registry.is_internal(Order)

    def test_unregistered_class_is_not_internal(self):
        domain, _ = _domain()
        assert not domain._domain_registry.is_internal(Unregistered)
