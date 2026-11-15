import pytest

from protean import Domain
from protean.adapters.event_store.message_db import MessageDBStore
from protean.exceptions import ConfigurationError
from protean.server.subscription_status import (
    SubscriptionStatus,
    collect_recovery_checkpoint_statuses,
    reset_recovery_checkpoint,
)
from protean.utils.eventing import MessageType
from tests.shared import MESSAGE_DB_PORT


@pytest.mark.message_db
class TestMessageDBEventStore:
    @pytest.fixture(autouse=True)
    def initialize_domain(self, test_domain):
        test_domain.init(traverse=False)

    def test_retrieving_message_store_from_domain(self, test_domain):
        assert test_domain.event_store is not None
        assert test_domain.event_store.store is not None
        assert isinstance(test_domain.event_store.store, MessageDBStore)

    def test_error_on_message_db_initialization(self):
        domain = Domain()
        domain.config["event_store"]["provider"] = "message_db"
        domain.config["event_store"]["database_uri"] = (
            f"postgresql://message_store@localhost:{MESSAGE_DB_PORT}/dummy"
        )
        domain.init(traverse=False)

        with pytest.raises(ConfigurationError) as exc:
            domain.event_store.store.write_message(
                "testStream-123",
                "Event1",
                {"foo": "bar"},
                {"domain": {"kind": "EVENT"}},
            )

        assert 'FATAL:  database "dummy" does not exist' in str(exc.value)

    def test_write_to_event_store(self, test_domain):
        position = test_domain.event_store.store.write_message(
            "testStream-123", "Event1", {"foo": "bar"}
        )

        assert position == 0

    def test_multiple_writes_to_event_store(self, test_domain):
        for i in range(5):
            position = test_domain.event_store.store.write_message(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        position = test_domain.event_store.store.write_message(
            "testStream-123", "Event1", {"foo": "bar"}
        )
        assert position == 5

    def test_reading_stream_message(self, test_domain):
        test_domain.event_store.store.write_message(
            "testStream-123", "Event1", {"foo": "bar"}
        )

        messages = test_domain.event_store.store.get_stream_messages("testStream-123")

        assert len(messages) == 1
        assert messages[0]["position"] == 0
        assert messages[0]["data"] == {"foo": "bar"}

    def test_reading_multiple_stream_messages(self, test_domain):
        for i in range(5):
            test_domain.event_store.store.write_message(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        messages = test_domain.event_store.store.get_stream_messages("testStream-123")

        assert len(messages) == 5
        assert messages[4]["data"] == {"foo": "bar4"}

    def test_reading_category_message(self, test_domain):
        test_domain.event_store.store.write_message(
            "testStream-123", "Event1", {"foo": "bar"}
        )

        messages = test_domain.event_store.store.get_category_messages("testStream")

        assert len(messages) == 1
        assert messages[0]["position"] == 0
        assert messages[0]["data"] == {"foo": "bar"}

    def test_reading_multiple_category_messages(self, test_domain):
        for i in range(5):
            test_domain.event_store.store.write_message(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        messages = test_domain.event_store.store.get_category_messages("testStream")

        assert len(messages) == 5
        assert messages[4]["data"] == {"foo": "bar4"}

    def test_reading_targeted_stream_messages(self, test_domain):
        for i in range(5):
            test_domain.event_store.store.write_message(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )
        for i in range(5):
            test_domain.event_store.store.write_message(
                "testStream-456", "Event1", {"foo": f"baz{i}"}
            )

        messages = test_domain.event_store.store.get_stream_messages("testStream-456")

        assert len(messages) == 5
        assert messages[4]["data"] == {"foo": "baz4"}

    def test_read_last_message(self, test_domain):
        for i in range(5):
            test_domain.event_store.store.write_message(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        message = test_domain.event_store.store.get_last_stream_message(
            "testStream-123"
        )
        assert message["position"] == 4

    def test_read_last_message_when_there_are_no_messages(self, test_domain):
        message = test_domain.event_store.store.get_last_stream_message("foo-bar")
        assert message is None

    def test_read_last_message_category_stream(self, test_domain):
        """read_last_message resolves a category stream (not just category-id).

        ``get_last_stream_message()`` returns None for category streams; the
        adapter must fall back to reading the category.
        """
        for i in range(5):
            test_domain.event_store.store.write_message(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        message = test_domain.event_store.store.get_last_category_message("testStream")
        assert message is not None
        assert message["data"]["foo"] == "bar4"  # the newest, not None

    def test_read_last_message_all_stream(self, test_domain):
        """read_last_message('$all') returns the newest global message.

        The exact failure: this returned None on Message-DB, making
        reconcile_outbox a permanent no-op (ADR-0015 crash-window recovery).
        """
        test_domain.event_store.store.write_message("streamA-1", "EventA", {"n": 1})
        test_domain.event_store.store.write_message("streamB-2", "EventB", {"n": 2})

        message = test_domain.event_store.store.get_last_message()
        assert message is not None  # was None before the fix
        # The newest global message is the *last one written* — asserted on
        # content, not by mirroring the fallback's own query. The client's
        # "$all" read has no ORDER BY, so the adapter must pick by global_position.
        assert message["type"] == "EventB"
        assert message["data"]["n"] == 2
        all_msgs = test_domain.event_store.store.get_all_messages(limit=1_000_000)
        assert message["global_position"] == max(m["global_position"] for m in all_msgs)

    def test_read_last_message_empty_category_and_all(self, test_domain):
        """The category fallback returns None (not IndexError) on an empty store.

        Guards the ``else None`` branch for the category/`$all` path that the
        fallback added — the existing None test only covers a *specific* stream.
        """
        store = test_domain.event_store.store
        assert store.get_last_message() is None
        assert store.get_last_category_message("neverWritten") is None

    def test_stream_head_position_empty_stream(self, test_domain):
        """stream_head_position returns -1 for a stream with no messages."""
        result = test_domain.event_store.store.stream_head_position("nonexistent")
        assert result == -1

    def test_stream_head_position_with_messages(self, test_domain):
        """stream_head_position returns global_position of the newest message."""
        for i in range(5):
            test_domain.event_store.store.write_message(
                "testStream-123", "Event1", {"foo": f"bar{i}"}
            )

        result = test_domain.event_store.store.stream_head_position("testStream")
        assert result >= 0

        # Should match the last category message's global_position
        all_msgs = test_domain.event_store.store.get_category_messages(
            "testStream", limit=1_000_000
        )
        assert result == all_msgs[-1]["global_position"]

    def test_stream_head_position_per_category(self, test_domain):
        """stream_head_position returns correct head per stream category."""
        for i in range(3):
            test_domain.event_store.store.write_message(
                "streamA-123", "EventA", {"idx": i}
            )
        for i in range(2):
            test_domain.event_store.store.write_message(
                "streamB-456", "EventB", {"idx": i}
            )

        head_a = test_domain.event_store.store.stream_head_position("streamA")
        head_b = test_domain.event_store.store.stream_head_position("streamB")

        assert head_a >= 0
        assert head_b >= 0
        assert head_a != head_b

    def test_recovery_reconstruction_round_trip(self, test_domain):
        """The recovery reconstruction, re-read, and reset run end to end against a
        real MessageDB store, not only the in-memory adapter, so an adapter-level
        cursor or tail-read mismatch in the shared paths would surface here."""
        store = test_domain.event_store.store
        event_meta = {"domain": {"kind": "EVENT"}}
        store.write_message("order-1", "Placed", {"n": 1}, event_meta)
        store.write_message("order-1", "Placed", {"n": 2}, event_meta)
        head = store.stream_head_position("order")

        rec_stream = "recovery-checkpoint-Handler-order"
        checkpoint_meta = {
            "domain": {
                "kind": MessageType.READ_POSITION.value,
                "origin_stream": "order",
            }
        }
        # One tracked position beyond the head (its message is gone -> stale) and
        # one at/below the head (its message is present -> healthy).
        store.write_message(
            rec_stream,
            "Checkpoint",
            {
                "watermark": 0,
                "unresolved": {
                    str(head + 3): {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                    "1": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            },
            checkpoint_meta,
        )

        status = SubscriptionStatus(
            name="sub",
            handler_name="Handler",
            subscription_type="event_store",
            stream_category="order",
            lag=0,
            pending=0,
            current_position=str(head),
            head_position=str(head),
            status="ok",
            consumer_count=0,
            dlq_depth=0,
            recovery_checkpoint_stream=rec_stream,
            failed_positions_stream="failed-Handler-order",
        )

        findings = collect_recovery_checkpoint_statuses(test_domain, [status])
        assert len(findings) == 1
        assert findings[0].verdict == "stale"
        assert findings[0].stale_positions == [head + 3]

        reset_recovery_checkpoint(test_domain, findings[0])

        # The stale entry is cleared and the healthy one preserved, so a later
        # scan is clean.
        assert collect_recovery_checkpoint_statuses(test_domain, [status]) == []

    def test_checkpoint_ahead_of_failed_stream_is_unknown(self, test_domain):
        """A restore that leaves the checkpoint watermark ahead of the failed
        stream is reported ``unknown``, exercised against a live MessageDB store so
        the adapter's tail-read of both streams (the ahead-of check) is covered,
        not only the in-memory one."""
        store = test_domain.event_store.store
        failed_stream = "failed-Handler-order"
        rec_stream = "recovery-checkpoint-Handler-order"
        record_meta = {
            "domain": {
                "kind": MessageType.READ_POSITION.value,
                "origin_stream": "order",
            }
        }
        # One Failed record survived the restore, at per-stream position 0.
        store.write_message(
            failed_stream,
            "Failed",
            {
                "position": 5,
                "retry_count": 1,
                "stream_name": None,
                "stream_position": None,
            },
            record_meta,
        )
        # A checkpoint whose watermark (10) sits past the failed-stream tail (0):
        # the checkpoint is ahead of the stream it references.
        store.write_message(
            rec_stream,
            "Checkpoint",
            {
                "watermark": 10,
                "unresolved": {
                    "99": {
                        "retry_count": 1,
                        "stream_name": None,
                        "stream_position": None,
                    },
                },
            },
            record_meta,
        )

        status = SubscriptionStatus(
            name="sub",
            handler_name="Handler",
            subscription_type="event_store",
            stream_category="order",
            lag=0,
            pending=0,
            current_position="0",
            head_position="0",
            status="ok",
            consumer_count=0,
            dlq_depth=0,
            recovery_checkpoint_stream=rec_stream,
            failed_positions_stream=failed_stream,
        )

        findings = collect_recovery_checkpoint_statuses(test_domain, [status])
        assert len(findings) == 1
        assert findings[0].verdict == "unknown"
        assert findings[0].stale_positions == []
