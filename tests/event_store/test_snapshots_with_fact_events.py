"""Regression for #1028.

Bulk ``create_snapshots()`` (and the underlying ``_stream_identifiers``) must
not treat an aggregate's ``{category}-fact-{id}`` fact-event streams as real
instances. With ``fact_events=True``, persisting writes a fact event to the
``-fact-`` stream; before the fix, instance discovery yielded a bogus
``fact-<id>`` identifier and reconstruction failed (fact events have no
``@apply`` handler).
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


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Promo, is_event_sourced=True, fact_events=True)
    test_domain.register(PromoLaunched, part_of=Promo)
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


def _add_promos(test_domain, count):
    repo = test_domain.repository_for(Promo)
    ids = []
    for i in range(count):
        pid = str(uuid4())
        ids.append(pid)
        with UnitOfWork():
            repo.add(Promo.launch(promo_id=pid, name=f"Promo {i}"))
    return ids


@pytest.mark.eventstore
def test_stream_identifiers_excludes_fact_streams(test_domain):
    """`_stream_identifiers` returns only real instance ids, not `fact-<id>`."""
    ids = _add_promos(test_domain, 2)

    identifiers = test_domain.event_store.store._stream_identifiers("test::promo")

    assert sorted(identifiers) == sorted(ids)
    assert not any(i.startswith("fact-") for i in identifiers)


@pytest.mark.eventstore
def test_create_snapshots_handles_fact_events_aggregate(test_domain):
    """Bulk snapshotting succeeds and snapshots only real instances."""
    ids = _add_promos(test_domain, 3)

    # Before the fix this raised IncorrectUsageError on the `-fact-` streams.
    count = test_domain.create_snapshots(Promo)
    assert count == 3

    for pid in ids:
        snapshot = test_domain.event_store.store._read_last_message(
            f"test::promo:snapshot-{pid}"
        )
        assert snapshot is not None
