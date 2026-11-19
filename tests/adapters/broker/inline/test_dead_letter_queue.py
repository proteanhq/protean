"""Tests for the dead-letter queue of InlineBroker.

The broker keeps a dead-lettered message as an ordinary message on
``{stream}:dlq`` with a ``_dlq_metadata`` record, the same shape the engine
writes, so every ``DeadLetterQueuePort`` member reads and changes that stream.
"""

from datetime import UTC, datetime, timedelta

import pytest

from tests.shared import FrozenClock

STREAM = "test_stream"
DLQ_STREAM = f"{STREAM}:dlq"
GROUP = "test_consumer_group"
START = datetime(2026, 11, 19, 12, 0, tzinfo=UTC)


@pytest.fixture
def clock(test_domain):
    frozen = FrozenClock(START)
    test_domain.clock = frozen
    return frozen


def _dead_letter(broker, payload, group=GROUP, stream=STREAM):
    """Publish ``payload`` and nack it past a zero retry ceiling."""
    broker._adapter._max_retries = 0
    identifier = broker.publish(stream, payload)
    assert broker.get_next(stream, group) is not None
    assert broker.nack(stream, identifier, group) is True
    return identifier


def _engine_entry(original_id, failed_at, **metadata):
    """Build a DLQ message in the shape the engine's subscription writes.

    The engine's record has no ``failure_reason`` key.
    """
    return {
        "data": original_id,
        "_dlq_metadata": {
            "original_stream": STREAM,
            "original_id": original_id,
            "consumer_group": "app.Handler",
            "consumer": "app.Handler-1",
            "failed_at": failed_at,
            "retry_count": 3,
            **metadata,
        },
    }


class TestTheRetryCeilingDeadLetters:
    def test_the_entry_is_a_message_on_the_dlq_stream(self, broker, clock):
        identifier = _dead_letter(broker, {"foo": "bar"})

        [(dlq_id, message)] = broker._adapter._messages[DLQ_STREAM]
        assert message == {
            "foo": "bar",
            "_dlq_metadata": {
                "original_stream": STREAM,
                "original_id": identifier,
                "consumer_group": GROUP,
                "failure_reason": "max_retries_exceeded",
                "failed_at": START.isoformat(),
                "retry_count": 1,
            },
        }
        assert dlq_id != identifier

    def test_dlq_list_reads_the_entry(self, broker, clock):
        identifier = _dead_letter(broker, {"foo": "bar"})

        [entry] = broker.dlq_list([DLQ_STREAM])

        assert entry.original_id == identifier
        assert entry.stream == STREAM
        assert entry.consumer_group == GROUP
        assert entry.failure_reason == "max_retries_exceeded"
        assert entry.failed_at == START.isoformat()
        assert entry.retry_count == 1
        assert entry.dlq_stream == DLQ_STREAM

    def test_the_dead_lettered_message_is_not_redelivered(self, broker):
        _dead_letter(broker, {"foo": "bar"})

        assert broker.get_next(STREAM, GROUP) is None

    def test_every_exhausted_message_is_kept(self, broker):
        identifiers = [_dead_letter(broker, {"n": n}) for n in range(5)]

        entries = broker.dlq_list([DLQ_STREAM])

        assert sorted(e.original_id for e in entries) == sorted(identifiers)

    def test_each_entry_names_the_group_that_failed_it(self, broker):
        broker._adapter._max_retries = 0
        identifier = broker.publish(STREAM, {"foo": "bar"})
        assert broker.get_next(STREAM, "group1") is not None
        assert broker.get_next(STREAM, "group2") is not None

        broker.nack(STREAM, identifier, "group1")
        broker.ack(STREAM, identifier, "group2")

        [entry] = broker.dlq_list([DLQ_STREAM])
        assert entry.consumer_group == "group1"

    def test_a_disabled_dlq_discards_the_message(self, broker):
        broker._adapter._enable_dlq = False

        _dead_letter(broker, {"foo": "bar"})

        assert broker.dlq_depth(DLQ_STREAM) == 0
        assert DLQ_STREAM not in broker._adapter._messages


class TestTheTimeoutDeadLetters:
    def test_a_stale_message_is_dead_lettered_as_timeout(self, broker, clock):
        broker._adapter._message_timeout = 0.0
        identifier = broker.publish(STREAM, {"foo": "bar"})
        assert broker.get_next(STREAM, GROUP) is not None

        broker._adapter._cleanup_stale_messages(GROUP, -1.0)

        [entry] = broker.dlq_list([DLQ_STREAM])
        assert entry.original_id == identifier
        assert entry.failure_reason == "timeout"
        assert entry.failed_at == START.isoformat()


class TestDepth:
    def test_depth_counts_the_entries(self, broker):
        for n in range(3):
            _dead_letter(broker, {"n": n})

        assert broker.dlq_depth(DLQ_STREAM) == 3

    def test_depth_counts_engine_written_entries(self, broker):
        broker.publish(DLQ_STREAM, _engine_entry("a", START.isoformat()))
        broker.publish(DLQ_STREAM, _engine_entry("b", START.isoformat()))

        assert broker.dlq_depth(DLQ_STREAM) == 2

    def test_depth_of_an_unknown_stream_is_zero(self, broker):
        assert broker.dlq_depth("missing:dlq") == 0


class TestEngineWrittenEntries:
    def test_an_entry_without_a_failure_reason_parses_as_unknown(self, broker):
        broker.publish(DLQ_STREAM, _engine_entry("orig-1", START.isoformat()))

        [entry] = broker.dlq_list([DLQ_STREAM])

        assert entry.original_id == "orig-1"
        assert entry.consumer_group == "app.Handler"
        assert entry.failure_reason == "unknown"
        assert entry.retry_count == 3


class TestTrim:
    def _two_entries(self, broker, clock):
        """Dead-letter one message at ``START`` and one an hour later."""
        _dead_letter(broker, {"n": "old"})
        clock.advance(timedelta(hours=1))
        _dead_letter(broker, {"n": "new"})

    def test_a_cutoff_before_every_entry_removes_nothing(self, broker, clock):
        self._two_entries(broker, clock)

        removed = broker.dlq_trim(DLQ_STREAM, START - timedelta(seconds=1))

        assert removed == 0
        assert broker.dlq_depth(DLQ_STREAM) == 2

    def test_a_cutoff_between_entries_removes_the_older(self, broker, clock):
        self._two_entries(broker, clock)

        removed = broker.dlq_trim(DLQ_STREAM, START + timedelta(minutes=30))

        assert removed == 1
        [entry] = broker.dlq_list([DLQ_STREAM])
        assert entry.payload["n"] == "new"

    def test_a_cutoff_after_every_entry_removes_all(self, broker, clock):
        self._two_entries(broker, clock)

        removed = broker.dlq_trim(DLQ_STREAM, START + timedelta(hours=2))

        assert removed == 2
        assert broker.dlq_depth(DLQ_STREAM) == 0

    def test_an_entry_failed_at_the_cutoff_is_kept(self, broker, clock):
        _dead_letter(broker, {"n": 1})

        assert broker.dlq_trim(DLQ_STREAM, START) == 0
        assert broker.dlq_depth(DLQ_STREAM) == 1

    def test_a_cutoff_in_another_time_zone_compares_the_instant(self, broker, clock):
        _dead_letter(broker, {"n": 1})
        later = (START + timedelta(minutes=1)).astimezone(
            datetime.now().astimezone().tzinfo
        )

        assert broker.dlq_trim(DLQ_STREAM, later) == 1

    @pytest.mark.parametrize(
        "failed_at",
        [None, 12345, "not a time", "2026-01-01T00:00:00"],
        ids=["missing", "not-a-string", "unparseable", "naive"],
    )
    def test_an_entry_without_a_usable_failed_at_is_kept(self, broker, failed_at):
        message = _engine_entry("orig-1", failed_at)
        if failed_at is None:
            del message["_dlq_metadata"]["failed_at"]
        broker.publish(DLQ_STREAM, message)
        broker.publish(DLQ_STREAM, _engine_entry("orig-2", "2026-01-01T00:00:00+00:00"))

        removed = broker.dlq_trim(DLQ_STREAM, START)

        assert removed == 1
        [entry] = broker.dlq_list([DLQ_STREAM])
        assert entry.original_id == "orig-1"

    def test_a_naive_cutoff_is_rejected(self, broker):
        with pytest.raises(ValueError, match="timezone-aware"):
            broker.dlq_trim(DLQ_STREAM, datetime(2026, 1, 1))

    def test_trimming_an_unknown_stream_removes_nothing(self, broker):
        assert broker.dlq_trim("missing:dlq", START) == 0


class TestReplay:
    def test_replay_republishes_without_the_metadata(self, broker):
        _dead_letter(broker, {"foo": "bar"})
        [entry] = broker.dlq_list([DLQ_STREAM])

        assert broker.dlq_replay(DLQ_STREAM, entry.dlq_id, STREAM) is True

        assert broker.dlq_depth(DLQ_STREAM) == 0
        retrieved = broker.get_next(STREAM, GROUP)
        assert retrieved is not None
        assert retrieved[1] == {"foo": "bar"}

    def test_replaying_an_unknown_id_returns_false(self, broker):
        _dead_letter(broker, {"foo": "bar"})

        assert broker.dlq_replay(DLQ_STREAM, "missing", STREAM) is False
        assert broker.dlq_depth(DLQ_STREAM) == 1

    def test_replay_all_republishes_every_entry(self, broker):
        for n in range(3):
            _dead_letter(broker, {"n": n})

        assert broker.dlq_replay_all(DLQ_STREAM, "target") == 3

        assert broker.dlq_depth(DLQ_STREAM) == 0
        replayed = [broker.get_next("target", GROUP) for _ in range(3)]
        assert [message for _, message in replayed] == [{"n": 0}, {"n": 1}, {"n": 2}]

    def test_a_replayed_message_is_not_dead_lettered_again_by_the_replay(self, broker):
        _dead_letter(broker, {"foo": "bar"})

        broker.dlq_replay_all(DLQ_STREAM, STREAM)

        assert broker.dlq_depth(DLQ_STREAM) == 0


class TestPurge:
    def test_purge_removes_every_entry(self, broker):
        for n in range(4):
            _dead_letter(broker, {"n": n})

        assert broker.dlq_purge(DLQ_STREAM) == 4
        assert broker.dlq_depth(DLQ_STREAM) == 0

    def test_purging_an_unknown_stream_removes_nothing(self, broker):
        assert broker.dlq_purge("missing:dlq") == 0


class TestAGroupReadingTheDLQStream:
    """A consumer group can read ``{stream}:dlq`` like any stream. Removing
    entries before its position must not make it skip an unread entry."""

    READER = "dlq-reader"

    def _three_entries_one_read(self, broker, clock):
        for n in range(3):
            _dead_letter(broker, {"n": n})
            clock.advance(timedelta(hours=1))
        first = broker.get_next(DLQ_STREAM, self.READER)
        assert first is not None
        broker.ack(DLQ_STREAM, first[0], self.READER)

    def _next_n(self, broker):
        retrieved = broker.get_next(DLQ_STREAM, self.READER)
        return None if retrieved is None else retrieved[1]["n"]

    def test_trim_keeps_the_next_unread_entry(self, broker, clock):
        self._three_entries_one_read(broker, clock)

        assert broker.dlq_trim(DLQ_STREAM, START + timedelta(minutes=30)) == 1

        assert self._next_n(broker) == 1

    def test_replay_keeps_the_next_unread_entry(self, broker, clock):
        self._three_entries_one_read(broker, clock)
        [first] = [e for e in broker.dlq_list([DLQ_STREAM]) if e.payload["n"] == 0]

        assert broker.dlq_replay(DLQ_STREAM, first.dlq_id, "target") is True

        assert self._next_n(broker) == 1

    def test_removing_an_unread_entry_leaves_the_position(self, broker, clock):
        self._three_entries_one_read(broker, clock)
        [second] = [e for e in broker.dlq_list([DLQ_STREAM]) if e.payload["n"] == 1]

        assert broker.dlq_replay(DLQ_STREAM, second.dlq_id, "target") is True

        assert self._next_n(broker) == 2

    def test_purge_moves_the_position_to_the_start(self, broker, clock):
        self._three_entries_one_read(broker, clock)
        broker.dlq_purge(DLQ_STREAM)

        _dead_letter(broker, {"n": 3})

        assert self._next_n(broker) == 3

    def test_a_group_on_the_dlq_of_the_dlq_keeps_its_position(self, broker, clock):
        self._three_entries_one_read(broker, clock)
        nested = f"{DLQ_STREAM}:dlq"
        broker.publish(nested, {"n": "nested"})
        assert broker.get_next(nested, self.READER) is not None
        position_key = f"{nested}:{self.READER}"
        before = broker._adapter._consumer_positions[position_key]

        broker.dlq_purge(DLQ_STREAM)

        assert broker._adapter._consumer_positions[position_key] == before
