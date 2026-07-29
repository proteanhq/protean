"""Round-trip tests for the ``Outbox.partition_key`` field (#830, ADR-0028)."""

from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import (
    Outbox,
    invalid_partition_key_reason,
)


def _metadata(msg_id="msg-1", stream_category="test::order"):
    headers = MessageHeaders(id=msg_id, type="OrderPlaced", stream="test::order-1")
    return Metadata(headers=headers, domain=DomainMeta(stream_category=stream_category))


class TestPartitionKeyField:
    def test_create_message_stores_partition_key(self):
        message = Outbox.create_message(
            message_id="msg-1",
            stream_name="test::order-1",
            message_type="OrderPlaced",
            data={"order_id": "o-1"},
            metadata=_metadata(),
            partition_key="client-1",
        )
        assert message.partition_key == "client-1"

    def test_partition_key_defaults_to_none(self):
        message = Outbox.create_message(
            message_id="msg-2",
            stream_name="test::order-1",
            message_type="OrderPlaced",
            data={"order_id": "o-2"},
            metadata=_metadata("msg-2"),
        )
        assert message.partition_key is None


class TestInvalidPartitionKeyReason:
    def test_valid_key_returns_none(self):
        assert invalid_partition_key_reason("client-1", "backfill") is None

    def test_null_or_empty_rejected(self):
        assert invalid_partition_key_reason(None, "backfill") is not None
        assert invalid_partition_key_reason("", "backfill") is not None

    def test_colon_rejected(self):
        reason = invalid_partition_key_reason("a:b", "backfill")
        assert reason is not None
        assert "colon" in reason

    def test_dlq_token_rejected(self):
        assert invalid_partition_key_reason("dlq", "backfill") is not None

    def test_configured_backfill_suffix_rejected(self):
        # The reserved suffix is config-dependent, not hardcoded.
        assert invalid_partition_key_reason("mylane", "mylane") is not None
        # ...and a key equal to the default suffix is fine under a custom one.
        assert invalid_partition_key_reason("backfill", "mylane") is None

    def test_sentinel_form_rejected(self):
        assert invalid_partition_key_reason("__partitions__", "backfill") is not None
        assert invalid_partition_key_reason("__x__", "backfill") is not None

    def test_ordinary_double_underscore_prefix_allowed(self):
        # Only the fully __name__-delimited form is reserved; a leading-only or
        # trailing-only underscore run is a legitimate key.
        assert invalid_partition_key_reason("__leadingonly", "backfill") is None
        assert invalid_partition_key_reason("trailingonly__", "backfill") is None
