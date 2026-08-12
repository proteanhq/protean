"""The SQLAlchemy OCC commit path emits the trace the spec checks (:issue:`#1382`).

The version-guarded ``_update`` observes the same compare-and-set ``specs/OCC.tla``
models: a standalone update flushes ``UPDATE ... SET _version = base + 1 WHERE
_version = base`` and, if the row's live version already moved past the base, the
version check rejects it as an ``ExpectedVersionError``. With the recorder active,
each of those decisions is emitted with the raw values the spec talks about.

Two stale copies of one aggregate, saved in turn, produce the same shape the
Memory adapter's contention does: one ``committed`` advancing the version, then one
``conflicted`` against the same base. ``specs/check.sh`` validates the Memory log
against ``OCC.tla``; this pins that the SQLAlchemy path emits the matching raw
observations.

The updates go through the DAO directly rather than ``repository.add`` because
``add`` wraps its own Unit of Work, which defers the version-guarded flush to the
UoW commit; the standalone DAO path flushes inside ``_update``, where the outcome
is observable.
"""

import pytest

from protean import Domain, UnitOfWork
from protean.core.aggregate import BaseAggregate
from protean.exceptions import ExpectedVersionError
from protean.fields import Integer
from protean.utils import occ_trace
from tests.shared import POSTGRES_PORT

pytestmark = [pytest.mark.postgresql, pytest.mark.no_test_domain]


class OCCTraceCounter(BaseAggregate):
    value = Integer(default=0)


@pytest.fixture
def trace_domain():
    domain = Domain(
        name="OCC trace",
        config={
            "identity_type": "uuid",
            "databases": {
                "default": {
                    "provider": "postgresql",
                    "database_uri": (
                        f"postgresql://postgres:postgres@localhost:{POSTGRES_PORT}/postgres"
                    ),
                }
            },
        },
    )
    domain.register(OCCTraceCounter)
    domain.init(traverse=False)

    provider = domain.providers["default"]
    with domain.domain_context():
        # Materialize the model before create_all.
        domain.repository_for(OCCTraceCounter)._dao
        provider._metadata.create_all(provider._engine)
        try:
            yield domain
        finally:
            provider._metadata.drop_all(provider._engine)
            provider.close()


def test_update_emits_committed_then_conflicted(trace_domain):
    repo = trace_domain.repository_for(OCCTraceCounter)
    with UnitOfWork():
        seed = OCCTraceCounter(value=0)
        repo.add(seed)
    counter_id = seed.id

    # Two copies loaded at the same version, so the second save is stale.
    first = repo.get(counter_id)
    second = repo.get(counter_id)

    with occ_trace.capture() as events:
        first.value = 10
        repo._dao.save(first)  # standalone: flushes the guarded UPDATE, commits
        second.value = 20
        with pytest.raises(ExpectedVersionError):
            repo._dao.save(second)  # its base 0 no longer matches the stored 1
        recorded = list(events)

    assert [e["outcome"] for e in recorded] == ["committed", "conflicted"]
    assert {e["stream"] for e in recorded} == {f"occ_trace_counter:{counter_id}"}
    # Both writers read base 0; the winner advanced the stored version to 1, and
    # the loser observed that same version 1 that no longer matched its base.
    assert all(e["base"] == 0 for e in recorded), recorded
    assert all(e["version_after"] == 1 for e in recorded), recorded


def test_update_through_a_unit_of_work_records_nothing(trace_domain):
    """Under a UnitOfWork the version-guarded flush is deferred to the UoW commit,
    so ``_update`` cannot observe the compare-and-set outcome. Both SQL emits are
    gated on the standalone path for that reason, so a UoW update records nothing
    rather than a half-observed event (:issue:`#1382`)."""
    repo = trace_domain.repository_for(OCCTraceCounter)
    with UnitOfWork():
        seed = OCCTraceCounter(value=0)
        repo.add(seed)
    counter_id = seed.id

    with occ_trace.capture() as events:
        with UnitOfWork():
            counter = repo.get(counter_id)
            counter.value = 10
            repo.add(counter)
        recorded = list(events)

    assert recorded == [], recorded
