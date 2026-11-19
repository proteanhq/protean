"""The SQLAlchemy OCC commit path emits the trace the spec checks (:issue:`#1382`).

The version-guarded ``update`` observes the same compare-and-set ``specs/OCC.tla``
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
UoW commit; the standalone DAO path commits through ``SADatabase.commit``, where
the outcome is observable.
"""

import pytest
from sqlalchemy import text

from protean import Domain, UnitOfWork
from protean.core.aggregate import BaseAggregate
from protean.exceptions import ExpectedVersionError
from protean.fields import Integer
from protean.utils import occ_trace
from tests.shared import POSTGRES_PORT, provider_adapter

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

    provider = provider_adapter(domain, "default")
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
    so the standalone commit path never sees the compare-and-set outcome. Both SQL emits are
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

    A standalone ``update`` reads and commits back to back, so there is no window
    to race it single-threaded. This injects an out-of-band version bump *between*
    the read and the flush by wrapping ``SADatabase.commit`` for the session that
    holds the pending update, making the flush's
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

    provider = provider_adapter(domain, "default")
    provider_cls = type(provider)
    real_commit = provider_cls.commit

    def bump_then_commit(self, session):
        if not session.dirty:
            return real_commit(self, session)
        with provider._engine.connect() as other:
            other.execute(
                text(
                    "UPDATE occ_trace_counter SET _version = _version + 1 WHERE id = :id"
                ),
                {"id": str(counter_id)},
            )
            other.commit()
        return real_commit(self, session)

    monkeypatch.setattr(provider_cls, "commit", bump_then_commit)
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


def test_a_stale_update_through_a_unit_of_work_records_nothing(trace_domain):
    """The Unit of Work commits its session without ``SADatabase.commit``, so the
    trace could not record that commit. A refused update inside it records no
    ``conflicted`` either, which keeps the trace free of a conflict whose
    winning commit it never saw."""
    repo = trace_domain.repository_for(OCCTraceCounter)
    with UnitOfWork():
        seed = OCCTraceCounter(value=0)
        repo.add(seed)
    stale = repo.get(seed.id)
    with UnitOfWork():
        fresh = repo.get(seed.id)
        fresh.value = 1
        repo.add(fresh)

    with occ_trace.capture() as events:
        with pytest.raises(ExpectedVersionError):
            with UnitOfWork():
                stale.value = 2
                repo.add(stale)
        recorded = list(events)

    assert recorded == [], recorded


def _seed_counters(domain, count):
    repo = domain.repository_for(OCCTraceCounter)
    with UnitOfWork():
        counters = [OCCTraceCounter(value=0) for _ in range(count)]
        for counter in counters:
            repo.add(counter)
    return [counter.id for counter in counters]


def _stage_updates(domain, session, counter_ids):
    """Version-check and stage an update of each counter from base 0, with no
    statement sent before the caller flushes or commits ``session``."""
    repo = domain.repository_for(OCCTraceCounter)
    adapter = repo._dao._adapter
    with session.no_autoflush:
        for counter_id in counter_ids:
            entity = repo.get(counter_id)
            entity._version = entity._next_version
            entity.value = 5
            model = adapter.database_model_cls.from_entity(entity)
            adapter.update(session, model, expected_version=0)


def _bump_version(domain, counter_id):
    provider = provider_adapter(domain, "default")
    with provider._engine.connect() as other:
        other.execute(
            text("UPDATE occ_trace_counter SET _version = _version + 1 WHERE id = :id"),
            {"id": str(counter_id)},
        )
        other.commit()


def test_a_commit_that_checked_two_rows_records_no_conflict(trace_domain):
    """SQLAlchemy does not say which row lost the race, so ``SADatabase.commit``
    records nothing when the session version-checked two rows."""
    provider = provider_adapter(trace_domain, "default")
    first_id, second_id = _seed_counters(trace_domain, 2)

    with occ_trace.capture() as events:
        session = provider.new_session()
        try:
            _stage_updates(trace_domain, session, [first_id, second_id])
            _bump_version(trace_domain, first_id)
            with pytest.raises(ExpectedVersionError):
                provider.commit(session)
        finally:
            provider.rollback(session)
            session.close()
        recorded = list(events)

    assert recorded == [], recorded


@pytest.mark.parametrize("end", ["commit", "flush"])
def test_a_stale_session_that_checked_one_row_records_its_conflict(trace_domain, end):
    provider = provider_adapter(trace_domain, "default")
    (counter_id,) = _seed_counters(trace_domain, 1)

    with occ_trace.capture() as events:
        session = provider.new_session()
        try:
            _stage_updates(trace_domain, session, [counter_id])
            _bump_version(trace_domain, counter_id)
            with pytest.raises(ExpectedVersionError):
                getattr(provider, end)(session)
        finally:
            provider.rollback(session)
            session.close()
        recorded = list(events)

    assert [
        (e["stream"], e["base"], e["outcome"], e["version_after"]) for e in recorded
    ] == [(f"occ_trace_counter:{counter_id}", 0, "conflicted", None)]
