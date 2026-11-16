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
