"""Regression test.

Bulk ``create_snapshots()`` failed for event-sourced aggregates with
``fact_events=True``: persisting also writes a ``{category}-fact-{id}`` stream,
which instance discovery surfaced as a bogus ``fact-<id>`` identifier;
reconstructing it then failed (fact events have no ``@apply`` handler).

``create_snapshots`` now excludes fact streams, but only for aggregates that
actually emit fact events — so an ordinary instance whose identifier happens to
start with ``fact-`` is never wrongly skipped.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Identifier, String
from protean.port.event_store import BaseEventStore


class PromoLaunched(BaseEvent):
    promo_id: Identifier(required=True)
    name: String(required=True, max_length=50)


class Promo(BaseAggregate):
    """Event-sourced aggregate that emits fact events."""

    promo_id: Identifier(identifier=True)
    name: String(max_length=50, required=True)

    @classmethod
    def launch(cls, promo_id, name):
        promo = cls(promo_id=promo_id, name=name)
        promo.raise_(PromoLaunched(promo_id=promo_id, name=name))
        return promo

    @apply
    def launched(self, event: PromoLaunched):
        self.promo_id = event.promo_id
        self.name = event.name


class CouponIssued(BaseEvent):
    coupon_id: Identifier(required=True)
    code: String(required=True, max_length=50)


class Coupon(BaseAggregate):
    """Event-sourced aggregate WITHOUT fact events."""

    coupon_id: Identifier(identifier=True)
    code: String(max_length=50, required=True)

    @classmethod
    def issue(cls, coupon_id, code):
        coupon = cls(coupon_id=coupon_id, code=code)
        coupon.raise_(CouponIssued(coupon_id=coupon_id, code=code))
        return coupon

    @apply
    def issued(self, event: CouponIssued):
        self.coupon_id = event.coupon_id
        self.code = event.code


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Promo, is_event_sourced=True, fact_events=True)
    test_domain.register(PromoLaunched, part_of=Promo)
    test_domain.register(Coupon, is_event_sourced=True)
    test_domain.register(CouponIssued, part_of=Coupon)
    test_domain.init(traverse=False)


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("fact-abc123", True),
        ("fact-", True),  # degenerate: just the prefix
        ("abc123", False),
        ("factory-123", False),  # starts with "fact" but not "fact-"
        ("fact", False),  # missing the hyphen
        ("", False),
    ],
)
def test_is_fact_stream_identifier(identifier, expected):
    assert BaseEventStore._is_fact_stream_identifier(identifier) is expected


@pytest.mark.eventstore
def test_create_snapshots_handles_fact_events_aggregate(test_domain):
    """Bulk snapshotting succeeds and snapshots only real instances."""
    repo = test_domain.repository_for(Promo)
    ids = []
    for i in range(3):
        pid = str(uuid4())
        ids.append(pid)
        with UnitOfWork():
            repo.add(Promo.launch(promo_id=pid, name=f"Promo {i}"))

    # Before the fix this raised IncorrectUsageError on the ``-fact-`` streams.
    count = test_domain.create_snapshots(Promo)
    assert count == 3

    for pid in ids:
        snapshot = test_domain.event_store.store._read_last_message(
            f"test::promo:snapshot-{pid}"
        )
        assert snapshot is not None


@pytest.mark.eventstore
def test_create_snapshots_keeps_fact_prefixed_id_without_fact_events(test_domain):
    """An instance whose id starts with ``fact-`` is not skipped when the

    aggregate does not emit fact events (the exclusion is scoped to
    ``fact_events=True``).
    """
    coupon_id = "fact-special-001"
    repo = test_domain.repository_for(Coupon)
    with UnitOfWork():
        repo.add(Coupon.issue(coupon_id=coupon_id, code="SAVE10"))

    count = test_domain.create_snapshots(Coupon)
    assert count == 1

    snapshot = test_domain.event_store.store._read_last_message(
        f"test::coupon:snapshot-{coupon_id}"
    )
    assert snapshot is not None
