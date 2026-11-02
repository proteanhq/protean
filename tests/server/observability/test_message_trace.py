"""Tests for the MessageTrace dataclass."""

import json
from datetime import UTC, datetime

from protean.server.tracing import MessageTrace


def _minimal_trace(**overrides):
    fields = {
        "event": "handler.started",
        "domain": "test",
        "stream": "test::user",
        "message_id": "abc-123",
        "message_type": "UserRegistered",
        "status": "ok",
    }
    fields.update(overrides)
    return MessageTrace(**fields)


class TestMessageTraceCreation:
    def test_required_fields_with_defaults(self):
        """MessageTrace with only required fields: the timestamp auto-fills as
        timezone-aware ISO 8601, optional fields default to None, and metadata
        defaults to an empty dict that no other trace shares."""
        trace = _minimal_trace()
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
        assert trace.worker_id is None
        assert trace.metadata == {}
        assert isinstance(trace.metadata, dict)

        # No mutable default sharing
        other = _minimal_trace(event="b", message_id="2")
        trace.metadata["added"] = True
        assert "added" not in other.metadata

        # worker_id is null in JSON when not provided
        assert json.loads(trace.to_json())["worker_id"] is None

    def test_all_fields_populated(self):
        """MessageTrace keeps every optional field provided, including an
        explicit timestamp that auto-fill does not overwrite, and writes them
        to JSON."""
        trace = MessageTrace(
            event="handler.failed",
            domain="identity",
            stream="identity::customer",
            message_id="uuid-456",
            message_type="CustomerRegistered",
            status="error",
            handler="CustomerProjector",
            duration_ms=12.34,
            error="Something broke",
            metadata={"key": "value"},
            payload={"name": "Alice"},
            worker_id="CustomerProjector-docker-abc123-7890-ff00ee",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        assert trace.handler == "CustomerProjector"
        assert trace.duration_ms == 12.34
        assert trace.error == "Something broke"
        assert trace.metadata == {"key": "value"}
        assert trace.worker_id == "CustomerProjector-docker-abc123-7890-ff00ee"
        assert trace.timestamp == "2026-01-01T00:00:00+00:00"

        data = json.loads(trace.to_json())
        assert data["status"] == "error"
        assert data["error"] == "Something broke"
        assert data["handler"] == "CustomerProjector"
        assert data["payload"] == {"name": "Alice"}
        assert data["worker_id"] == "CustomerProjector-docker-abc123-7890-ff00ee"
        assert data["timestamp"] == "2026-01-01T00:00:00+00:00"


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
        now = datetime.now(UTC)
        trace = _minimal_trace(metadata={"time": now})
        # Should not raise
        json_str = trace.to_json()
        data = json.loads(json_str)
        # datetime converted to string
        assert isinstance(data["metadata"]["time"], str)
