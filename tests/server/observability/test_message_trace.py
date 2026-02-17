"""Tests for the MessageTrace dataclass."""

import json
from datetime import datetime, timezone

from protean.server.tracing import MessageTrace


class TestMessageTraceCreation:
    def test_required_fields_with_auto_timestamp(self):
        """MessageTrace with only required fields; timestamp auto-fills as UTC ISO 8601."""
        trace = MessageTrace(
            event="handler.started",
            domain="test",
            stream="test::user",
            message_id="abc-123",
            message_type="UserRegistered",
            status="ok",
        )
        assert trace.event == "handler.started"
        assert trace.domain == "test"
        assert trace.stream == "test::user"
        assert trace.message_id == "abc-123"
        assert trace.message_type == "UserRegistered"
        assert trace.status == "ok"

        # Timestamp auto-filled
        assert trace.timestamp != ""
        parsed = datetime.fromisoformat(trace.timestamp)
        assert parsed.tzinfo is not None  # Timezone-aware

        # Optional fields default
        assert trace.handler is None
        assert trace.duration_ms is None
        assert trace.error is None

    def test_all_fields_populated(self):
        """MessageTrace with all optional fields provided."""
        trace = MessageTrace(
            event="handler.completed",
            domain="identity",
            stream="identity::customer",
            message_id="uuid-456",
            message_type="CustomerRegistered",
            status="ok",
            handler="CustomerProjector",
            duration_ms=12.34,
            error=None,
            metadata={"key": "value"},
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert trace.handler == "CustomerProjector"
        assert trace.duration_ms == 12.34
        assert trace.error is None
        assert trace.metadata == {"key": "value"}
        assert trace.timestamp == "2026-01-01T00:00:00+00:00"

    def test_explicit_timestamp_preserved(self):
        """Providing a timestamp should not be overwritten by auto-fill."""
        explicit_ts = "2025-06-15T12:00:00+00:00"
        trace = MessageTrace(
            event="handler.started",
            domain="test",
            stream="test::user",
            message_id="abc",
            message_type="Foo",
            status="ok",
            timestamp=explicit_ts,
        )
        assert trace.timestamp == explicit_ts

    def test_default_metadata_is_empty_dict(self):
        """metadata defaults to an empty dict, not None."""
        trace = MessageTrace(
            event="handler.started",
            domain="test",
            stream="test::user",
            message_id="abc",
            message_type="Foo",
            status="ok",
        )
        assert trace.metadata == {}
        assert isinstance(trace.metadata, dict)

    def test_metadata_default_not_shared_across_instances(self):
        """Each trace gets its own metadata dict (no mutable default sharing)."""
        t1 = MessageTrace(
            event="a",
            domain="d",
            stream="s",
            message_id="1",
            message_type="T",
            status="ok",
        )
        t2 = MessageTrace(
            event="b",
            domain="d",
            stream="s",
            message_id="2",
            message_type="T",
            status="ok",
        )
        t1.metadata["added"] = True
        assert "added" not in t2.metadata


class TestMessageTraceSerialization:
    def test_to_json_roundtrip(self):
        """to_json produces valid JSON that round-trips correctly."""
        trace = MessageTrace(
            event="handler.completed",
            domain="test",
            stream="test::order",
            message_id="msg-789",
            message_type="OrderPlaced",
            status="ok",
            handler="OrderHandler",
            duration_ms=5.67,
            metadata={"retry": 1},
        )
        json_str = trace.to_json()
        data = json.loads(json_str)

        assert data["event"] == "handler.completed"
        assert data["domain"] == "test"
        assert data["stream"] == "test::order"
        assert data["message_id"] == "msg-789"
        assert data["message_type"] == "OrderPlaced"
        assert data["status"] == "ok"
        assert data["handler"] == "OrderHandler"
        assert data["duration_ms"] == 5.67
        assert data["error"] is None
        assert data["metadata"] == {"retry": 1}
        assert data["timestamp"] != ""

    def test_to_json_handles_non_serializable_metadata(self):
        """to_json uses default=str for non-JSON-serializable values."""
        now = datetime.now(timezone.utc)
        trace = MessageTrace(
            event="handler.started",
            domain="test",
            stream="test::user",
            message_id="abc",
            message_type="Foo",
            status="ok",
            metadata={"time": now},
        )
        # Should not raise
        json_str = trace.to_json()
        data = json.loads(json_str)
        # datetime converted to string
        assert isinstance(data["metadata"]["time"], str)

    def test_to_json_with_error_field(self):
        """to_json includes error field when present."""
        trace = MessageTrace(
            event="handler.failed",
            domain="test",
            stream="test::user",
            message_id="abc",
            message_type="Foo",
            status="error",
            error="Something broke",
        )
        data = json.loads(trace.to_json())
        assert data["error"] == "Something broke"
        assert data["status"] == "error"
