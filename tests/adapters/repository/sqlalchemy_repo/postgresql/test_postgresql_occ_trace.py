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
from sqlalchemy import text

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


def _provoke_standalone_flush_conflict(domain, monkeypatch):
    """Return a ``save()`` that hits a standalone flush-time version conflict.

    A standalone ``_update`` reads and flushes back to back, so there is no window
    to race it single-threaded. This injects an out-of-band version bump *between*
    the read and the flush by wrapping ``_commit_if_standalone``, making the flush's
    ``WHERE _version = 0`` match zero rows deterministically (the same trick as
    ``test_flush_time_version_conflict_raises_expected_version_error``, adapted to
    the standalone path)."""
    repo = domain.repository_for(OCCTraceCounter)
    with UnitOfWork():
        seed = OCCTraceCounter(value=0)
        repo.add(seed)
    counter_id = seed.id

    entity = repo.get(counter_id)  # loaded at version 0, before the patch below
    entity.value = 7

    provider = domain.providers["default"]
    dao_cls = type(repo._dao)
    real_commit = dao_cls._commit_if_standalone

    def bump_then_commit(self, conn):
        with provider._engine.connect() as other:
            other.execute(
                text(
                    "UPDATE occ_trace_counter SET _version = _version + 1 WHERE id = :id"
                ),
                {"id": str(counter_id)},
            )
            other.commit()
        return real_commit(self, conn)

    monkeypatch.setattr(dao_cls, "_commit_if_standalone", bump_then_commit)
    return counter_id, lambda: repo._dao.save(entity)


def test_standalone_flush_conflict_raises_expected_version_error(
    trace_domain, monkeypatch
):
    """A standalone flush that loses the version-id race raises StaleDataError; it
    must surface as ExpectedVersionError, matching the UoW path and _flush/_filter/
    _count, so callers see one optimistic-concurrency error everywhere
    (:issue:`#1382`)."""
    _, do_save = _provoke_standalone_flush_conflict(trace_domain, monkeypatch)
    with pytest.raises(ExpectedVersionError):
        do_save()  # no capture active: exercises the translation on its own


def test_standalone_flush_conflict_is_recorded_as_a_conflict(trace_domain, monkeypatch):
    """The losing standalone writer records a ``conflicted`` event against its base;
    the row was rolled back and the connection closed, so the resulting version is
    unknown and recorded as ``None`` (:issue:`#1382`)."""
    counter_id, do_save = _provoke_standalone_flush_conflict(trace_domain, monkeypatch)
    with occ_trace.capture() as events:
        with pytest.raises(ExpectedVersionError):
            do_save()
        recorded = list(events)

    assert [e["outcome"] for e in recorded] == ["conflicted"]
    assert recorded[0]["stream"] == f"occ_trace_counter:{counter_id}"
    assert recorded[0]["base"] == 0
    assert recorded[0]["version_after"] is None
