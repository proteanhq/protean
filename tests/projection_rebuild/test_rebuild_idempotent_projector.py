"""Rebuilding a projection whose projector is ``idempotent=True``.

Live delivery leaves a ``(message_id, handler)`` marker per event. A rebuild
replays the same messages, so unless it clears those markers with the rows,
every replayed event is skipped as a redelivery and the projection stays empty.
"""

import pytest

from protean import current_domain
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.exceptions import ObjectNotFoundError
from protean.fields import Identifier, Integer, String
from protean.utils import fqn
from protean.utils.projection_rebuilder import _truncate_projection


class Counter(BaseAggregate):
    name = String()

    def increment(self) -> None:
        self.raise_(Incremented(counter_id=self.id))


class Incremented(BaseEvent):
    counter_id = Identifier()


class Tally(BaseProjection):
    counter_id = Identifier(identifier=True)
    count = Integer(default=0)


class OtherTally(BaseProjection):
    counter_id = Identifier(identifier=True)
    count = Integer(default=0)


class CachedTally(BaseProjection):
    counter_id = Identifier(identifier=True)
    count = Integer(default=0)


def _bump(projection_cls: type[BaseProjection], counter_id: str) -> None:
    """Accumulate, so a replayed-and-skipped event shows up as a wrong count."""
    repo = current_domain.repository_for(projection_cls)
    try:
        row = repo.get(counter_id)
    except ObjectNotFoundError:
        row = projection_cls(counter_id=counter_id, count=0)
    row.count += 1
    repo.add(row)


class TallyProjector(BaseProjector):
    @on(Incremented)
    def on_incremented(self, event: Incremented) -> None:
        _bump(Tally, event.counter_id)


class OtherTallyProjector(BaseProjector):
    @on(Incremented)
    def on_incremented(self, event: Incremented) -> None:
        _bump(OtherTally, event.counter_id)


class CachedTallyProjector(BaseProjector):
    @on(Incremented)
    def on_incremented(self, event: Incremented) -> None:
        cache = current_domain.cache_for(CachedTally)
        cache.add(CachedTally(counter_id=event.counter_id, count=1))


TALLY_HANDLER = fqn(TallyProjector.on_incremented)
OTHER_HANDLER = fqn(OtherTallyProjector.on_incremented)


def _register(test_domain, *, idempotent: bool = True) -> None:
    test_domain.register(Counter)
    test_domain.register(Incremented, part_of=Counter)
    test_domain.register(Tally)
    test_domain.register(
        TallyProjector,
        projector_for=Tally,
        aggregates=[Counter],
        idempotent=idempotent,
    )
    test_domain.register(OtherTally)
    test_domain.register(
        OtherTallyProjector,
        projector_for=OtherTally,
        aggregates=[Counter],
        idempotent=True,
    )
    test_domain.init(traverse=False)
    # The `db` fixture creates tables before in-test registration, so the
    # projection and marker tables are created here.
    test_domain.setup_database()


def _populate() -> tuple[str, str]:
    """Two events for one counter, one for another, delivered live."""
    repo = current_domain.repository_for(Counter)
    first = Counter(name="first")
    first.increment()
    first.increment()
    repo.add(first)
    second = Counter(name="second")
    second.increment()
    repo.add(second)
    return first.id, second.id


def _counts(projection_cls: type[BaseProjection]) -> dict[str, int]:
    rows = current_domain.repository_for(projection_cls)._dao.query.all().items
    return {row.counter_id: row.count for row in rows}


def _marker_ids(handler: str) -> list[str]:
    repo = current_domain._get_processed_message_repo("default")
    rows = repo._dao.query.filter(handler=handler).all().items
    return sorted(row.message_id for row in rows)


def _stored_message_ids(test_domain) -> list[str]:
    messages = list(test_domain.event_store.store.read_all("test::counter"))
    return sorted(message.metadata.headers.id for message in messages)


def _assert_rebuild_restores_values(test_domain) -> None:
    _register(test_domain)
    first_id, second_id = _populate()
    assert _counts(Tally) == {first_id: 2, second_id: 1}
    assert len(_marker_ids(TALLY_HANDLER)) == 3

    result = test_domain.rebuild_projection(Tally)

    assert result.success
    assert result.events_dispatched == 3
    assert _counts(Tally) == {first_id: 2, second_id: 1}


def _assert_fresh_markers(test_domain) -> None:
    _register(test_domain)
    _populate()
    stored = _stored_message_ids(test_domain)
    assert len(stored) == 3
    before = _counts(Tally)

    test_domain.rebuild_projection(Tally)

    assert _marker_ids(TALLY_HANDLER) == stored

    # The fresh markers dedupe a redelivery after the rebuild.
    message = next(iter(test_domain.event_store.store.read_all("test::counter")))
    TallyProjector._handle(message)
    assert _counts(Tally) == before


def _assert_other_markers_survive(test_domain) -> None:
    _register(test_domain)
    _populate()
    marker_repo = current_domain._get_processed_message_repo("default")
    marker_repo.mark("unrelated-message", "some.other.Handler.method")
    other_markers = _marker_ids(OTHER_HANDLER)
    assert len(other_markers) == 3
    other_counts = _counts(OtherTally)

    test_domain.rebuild_projection(Tally)

    assert _marker_ids(OTHER_HANDLER) == other_markers
    assert _counts(OtherTally) == other_counts
    assert marker_repo.is_processed("unrelated-message", "some.other.Handler.method")


class TestRebuildIdempotentProjector:
    def test_rebuild_restores_the_read_model(self, test_domain):
        _assert_rebuild_restores_values(test_domain)

    def test_rebuild_writes_one_fresh_marker_per_replayed_event(self, test_domain):
        _assert_fresh_markers(test_domain)

    def test_rebuild_keeps_markers_of_other_handlers(self, test_domain):
        _assert_other_markers_survive(test_domain)

    def test_non_idempotent_projector_markers_are_left_alone(self, test_domain):
        _register(test_domain, idempotent=False)
        _populate()
        marker_repo = current_domain._get_processed_message_repo("default")
        marker_repo.mark("seeded-message", TALLY_HANDLER)

        result = test_domain.rebuild_projection(Tally)

        assert result.success
        assert marker_repo.is_processed("seeded-message", TALLY_HANDLER)

    def test_marker_store_is_not_touched_without_idempotent_projectors(
        self, test_domain, monkeypatch
    ):
        test_domain.register(Counter)
        test_domain.register(Incremented, part_of=Counter)
        test_domain.register(Tally)
        test_domain.register(TallyProjector, projector_for=Tally, aggregates=[Counter])
        test_domain.init(traverse=False)
        first_id, second_id = _populate()

        def _fail(provider_name):
            pytest.fail("marker store resolved for a non-idempotent rebuild")

        monkeypatch.setattr(test_domain, "_get_processed_message_repo", _fail)

        result = test_domain.rebuild_projection(Tally)

        assert result.success
        assert _counts(Tally) == {first_id: 2, second_id: 1}
        assert test_domain._infrastructure.processed_message_repos == {}

    def test_cache_backed_projection_does_not_touch_the_marker_store(
        self, test_domain, monkeypatch
    ):
        test_domain.register(Counter)
        test_domain.register(Incremented, part_of=Counter)
        test_domain.register(CachedTally, cache="default")
        test_domain.register(
            CachedTallyProjector,
            projector_for=CachedTally,
            aggregates=[Counter],
            idempotent=True,
        )
        test_domain.init(traverse=False)
        first_id, _ = _populate()
        cache = test_domain.cache_for(CachedTally)
        assert cache.get(f"cached_tally:::{first_id}") is not None

        def _fail(provider_name):
            pytest.fail("marker store resolved for a cache-backed projection")

        # Dispatch looks up the marker store on its own (and finds none for a
        # cache projection), so only the truncate step is held to the spy.
        with monkeypatch.context() as patched:
            patched.setattr(test_domain, "_get_processed_message_repo", _fail)
            _truncate_projection(test_domain, CachedTally, [CachedTallyProjector])
        assert cache.get(f"cached_tally:::{first_id}") is None

        result = test_domain.rebuild_projection(CachedTally)

        assert result.success
        assert result.events_dispatched == 3
        assert cache.get(f"cached_tally:::{first_id}") is not None


@pytest.mark.database
class TestRebuildIdempotentProjectorRelational:
    def test_rebuild_restores_the_read_model(self, test_domain):
        _assert_rebuild_restores_values(test_domain)

    def test_rebuild_writes_one_fresh_marker_per_replayed_event(self, test_domain):
        _assert_fresh_markers(test_domain)

    def test_rebuild_keeps_markers_of_other_handlers(self, test_domain):
        _assert_other_markers_survive(test_domain)

    def test_failed_marker_delete_rolls_back_the_row_delete(
        self, test_domain, monkeypatch
    ):
        if type(test_domain.providers["default"]).__name__ == "MemoryProvider":
            pytest.skip("only a relational provider rolls back the row delete")

        _register(test_domain)
        first_id, second_id = _populate()
        marker_dao = current_domain._get_processed_message_repo("default")._dao
        calls = []

        def _boom(criteria=None):
            calls.append(criteria)
            raise RuntimeError("marker delete failed")

        monkeypatch.setattr(marker_dao, "_delete_all", _boom)

        with pytest.raises(RuntimeError, match="marker delete failed"):
            test_domain.rebuild_projection(Tally)

        assert len(calls) == 1
        monkeypatch.undo()
        assert _counts(Tally) == {first_id: 2, second_id: 1}
        assert len(_marker_ids(TALLY_HANDLER)) == 3
