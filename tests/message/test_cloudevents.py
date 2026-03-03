"""Tests for CloudEvents v1.0 serialization on Message.

Tests cover:
- ``to_cloudevent()`` — producing CloudEvents from Protean messages
- ``from_cloudevent()`` — consuming CloudEvents into Protean messages
- Round-trip preservation of data and metadata
- Edge cases for source derivation, subject extraction, and metadata branches
"""

from datetime import datetime, timezone
from unittest.mock import PropertyMock, patch
from uuid import uuid4

import pytest

from protean import apply
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.event import BaseEvent
from protean.fields import Identifier, String
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageEnvelope,
    MessageHeaders,
    Metadata,
    TraceParent,
)


# ── Domain elements ──────────────────────────────────────────────────


class Register(BaseCommand):
    id: Identifier(identifier=True)
    email: String()
    name: String()


class Registered(BaseEvent):
    id: Identifier(identifier=True)
    email: String()
    name: String()


class User(BaseAggregate):
    email: String()
    name: String()

    @apply
    def on_registered(self, event: Registered) -> None:
        self.email = event.email
        self.name = event.name


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Register, part_of=User)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


# ── Helpers ──────────────────────────────────────────────────────────


def _make_event_message() -> tuple[Message, str]:
    """Create a Message from a raised event and return (message, identifier)."""
    identifier = str(uuid4())
    user = User(id=identifier, email="john@example.com", name="John Doe")
    user.raise_(Registered(id=identifier, email="john@example.com", name="John Doe"))
    message = Message.from_domain_object(user._events[-1])
    return message, identifier


def _make_command_message(test_domain) -> tuple[Message, str]:
    """Create a Message from an enriched command and return (message, identifier)."""
    identifier = str(uuid4())
    command = Register(id=identifier, email="john@example.com", name="John Doe")
    enriched = test_domain._enrich_command(command, asynchronous=True)
    message = Message.from_domain_object(enriched)
    return message, identifier


# ═══════════════════════════════════════════════════════════════════════
# to_cloudevent()
# ═══════════════════════════════════════════════════════════════════════


class TestToCloudeventRequired:
    """to_cloudevent() produces all CloudEvents required attributes."""

    def test_required_attributes_present(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert "specversion" in ce
        assert "id" in ce
        assert "type" in ce
        assert "source" in ce

    def test_specversion_is_1_0(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert ce["specversion"] == "1.0"

    def test_id_matches_header(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert ce["id"] == message.metadata.headers.id

    def test_type_matches_header(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert ce["type"] == message.metadata.headers.type
        assert ce["type"] == Registered.__type__

    def test_data_matches_message(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert ce["data"] == message.data

    def test_datacontenttype_is_json(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert ce["datacontenttype"] == "application/json"


class TestToCloudeventSource:
    """to_cloudevent() derives source via the fallback chain."""

    def test_source_derived_from_domain_name(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        # Default test domain name → urn:protean:<normalized_name>
        assert ce["source"].startswith("urn:protean:")

    def test_source_from_configured_uri(self, test_domain):
        test_domain.config["source_uri"] = "https://orders.example.com"
        try:
            message, _ = _make_event_message()
            ce = message.to_cloudevent()

            assert ce["source"] == "https://orders.example.com"
        finally:
            test_domain.config["source_uri"] = None


class TestToCloudeventSubject:
    """to_cloudevent() extracts aggregate ID as subject from stream name."""

    def test_subject_from_event_stream(self):
        message, identifier = _make_event_message()
        ce = message.to_cloudevent()

        assert ce["subject"] == identifier

    def test_subject_from_command_stream(self, test_domain):
        message, identifier = _make_command_message(test_domain)
        ce = message.to_cloudevent()

        assert ce["subject"] == identifier


class TestToCloudeventOptional:
    """to_cloudevent() includes optional attributes when available."""

    def test_time_present_as_iso_string(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert "time" in ce
        # Should be parseable as ISO 8601
        parsed = datetime.fromisoformat(ce["time"])
        assert parsed.tzinfo is not None  # Must be timezone-aware

    def test_null_values_omitted(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        for value in ce.values():
            assert value is not None


class TestToCloudeventExtensions:
    """to_cloudevent() includes Protean-namespaced extensions."""

    def test_proteankind_present(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert ce["proteankind"] == "EVENT"

    def test_sequence_present(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert "sequence" in ce
        assert ce["sequence"] == message.metadata.domain.sequence_id

    def test_proteansequencetype_for_es_events(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        # ES aggregate → integer sequence (no dot)
        assert ce["proteansequencetype"] == "Integer"

    def test_proteanchecksum_present(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert "proteanchecksum" in ce
        assert ce["proteanchecksum"] == message.metadata.envelope.checksum

    def test_correlation_id_present_when_set(self, test_domain):
        """Commands processed via domain.process() get correlation_id."""
        identifier = str(uuid4())
        command = Register(id=identifier, email="j@ex.com", name="J")
        test_domain.process(command, correlation_id="ext-corr-123")

        messages = test_domain.event_store.store.read("user:command")
        message = messages[-1]
        ce = message.to_cloudevent()

        assert ce["proteancorrelationid"] == "ext-corr-123"

    def test_traceparent_present_when_set(self):
        """When traceparent is set, it appears as W3C string."""
        message, _ = _make_event_message()
        # Traceparent is not set by default in test events
        ce = message.to_cloudevent()

        # If traceparent was set, it would be a W3C string
        # By default it's not set, so should be absent
        if message.metadata.headers.traceparent:
            assert "traceparent" in ce
        else:
            assert "traceparent" not in ce

    def test_user_extensions_merged(self, test_domain):
        """Extensions from enrichers appear in CloudEvent output."""

        def add_tenant(event, aggregate):
            return {"tenant_id": "tenant-abc"}

        test_domain.register_event_enricher(add_tenant)

        message, _ = _make_event_message()
        ce = message.to_cloudevent()

        assert ce["tenant_id"] == "tenant-abc"


# ═══════════════════════════════════════════════════════════════════════
# from_cloudevent()
# ═══════════════════════════════════════════════════════════════════════


class TestFromCloudeventValid:
    """from_cloudevent() parses valid CloudEvents."""

    def test_minimal_cloudevent(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.order.created",
            "source": "https://orders.example.com",
            "data": {"order_id": "abc123"},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.headers.id == "evt-001"
        assert message.metadata.headers.type == "com.example.order.created"
        assert message.data == {"order_id": "abc123"}

    def test_full_cloudevent(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-002",
            "type": "com.example.user.registered",
            "source": "https://users.example.com",
            "time": "2026-03-02T10:30:00+00:00",
            "subject": "user-abc123",
            "datacontenttype": "application/json",
            "data": {"user_id": "abc123", "email": "j@ex.com"},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.headers.id == "evt-002"
        assert message.metadata.headers.type == "com.example.user.registered"
        assert message.metadata.headers.time == datetime(
            2026, 3, 2, 10, 30, tzinfo=timezone.utc
        )
        assert message.data == {"user_id": "abc123", "email": "j@ex.com"}

    def test_empty_data_defaults_to_empty_dict(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-003",
            "type": "com.example.ping",
            "source": "/ping",
        }
        message = Message.from_cloudevent(ce)

        assert message.data == {}


class TestFromCloudeventPreservation:
    """from_cloudevent() preserves CE-specific attributes in extensions."""

    def test_source_preserved_in_extensions(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "https://orders.example.com",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.extensions["ce_source"] == "https://orders.example.com"

    def test_subject_preserved_in_extensions(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "subject": "order-abc123",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.extensions["ce_subject"] == "order-abc123"

    def test_datacontenttype_preserved_when_not_json(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "datacontenttype": "application/xml",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.extensions["ce_datacontenttype"] == "application/xml"

    def test_datacontenttype_not_preserved_when_json(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "datacontenttype": "application/json",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert "ce_datacontenttype" not in message.metadata.extensions

    def test_dataschema_preserved(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "dataschema": "https://schema.example.com/user/v1",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert (
            message.metadata.extensions["ce_dataschema"]
            == "https://schema.example.com/user/v1"
        )

    def test_unknown_extensions_preserved(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "customext1": "value1",
            "customext2": 42,
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.extensions["customext1"] == "value1"
        assert message.metadata.extensions["customext2"] == 42


class TestFromCloudeventProteanExtensions:
    """from_cloudevent() maps Protean-namespaced extensions back."""

    def test_traceparent_mapped(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        tp = message.metadata.headers.traceparent
        assert tp is not None
        assert tp.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert tp.parent_id == "00f067aa0ba902b7"
        assert tp.sampled is True

    def test_correlation_and_causation_mapped(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "proteancorrelationid": "corr-abc",
            "proteancausationid": "cause-xyz",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.domain.correlation_id == "corr-abc"
        assert message.metadata.domain.causation_id == "cause-xyz"

    def test_checksum_mapped(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "proteanchecksum": "abc123def456",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.envelope.checksum == "abc123def456"

    def test_kind_mapped(self):
        ce = {
            "specversion": "1.0",
            "id": "cmd-001",
            "type": "com.example.test",
            "source": "/test",
            "proteankind": "COMMAND",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.domain.kind == "COMMAND"

    def test_kind_defaults_to_event(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.domain.kind == "EVENT"

    def test_sequence_mapped(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "sequence": "42",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.domain.sequence_id == "42"


class TestFromCloudeventChecksum:
    """from_cloudevent() handles checksum correctly."""

    def test_checksum_computed_when_not_provided(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "data": {"key": "value"},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.envelope.checksum is not None
        assert message.verify_integrity()

    def test_provided_checksum_used(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "proteanchecksum": "custom-checksum",
            "data": {"key": "value"},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.envelope.checksum == "custom-checksum"


class TestFromCloudeventValidation:
    """from_cloudevent() validates required attributes."""

    def test_raises_on_missing_specversion(self):
        ce = {
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
        }
        with pytest.raises(ValueError, match="specversion"):
            Message.from_cloudevent(ce)

    def test_raises_on_missing_id(self):
        ce = {
            "specversion": "1.0",
            "type": "com.example.test",
            "source": "/test",
        }
        with pytest.raises(ValueError, match="id"):
            Message.from_cloudevent(ce)

    def test_raises_on_missing_type(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "source": "/test",
        }
        with pytest.raises(ValueError, match="type"):
            Message.from_cloudevent(ce)

    def test_raises_on_missing_source(self):
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
        }
        with pytest.raises(ValueError, match="source"):
            Message.from_cloudevent(ce)

    def test_raises_on_missing_multiple(self):
        ce = {"specversion": "1.0"}
        with pytest.raises(ValueError, match="id.*type.*source"):
            Message.from_cloudevent(ce)

    def test_raises_on_wrong_specversion(self):
        ce = {
            "specversion": "2.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
        }
        with pytest.raises(ValueError, match="Unsupported.*2.0"):
            Message.from_cloudevent(ce)


# ═══════════════════════════════════════════════════════════════════════
# Round-trip tests
# ═══════════════════════════════════════════════════════════════════════


class TestRoundTrip:
    """from_cloudevent(msg.to_cloudevent()) preserves key data."""

    def test_data_preserved(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()
        restored = Message.from_cloudevent(ce)

        assert restored.data == message.data

    def test_headers_id_preserved(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()
        restored = Message.from_cloudevent(ce)

        assert restored.metadata.headers.id == message.metadata.headers.id

    def test_headers_type_preserved(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()
        restored = Message.from_cloudevent(ce)

        assert restored.metadata.headers.type == message.metadata.headers.type

    def test_time_preserved(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()
        restored = Message.from_cloudevent(ce)

        # Time round-trips through ISO format string
        assert restored.metadata.headers.time is not None
        assert (
            restored.metadata.headers.time.isoformat()
            == message.metadata.headers.time.isoformat()
        )

    def test_correlation_id_preserved(self, test_domain):
        identifier = str(uuid4())
        command = Register(id=identifier, email="j@ex.com", name="J")
        test_domain.process(command, correlation_id="corr-round-trip")

        messages = test_domain.event_store.store.read("user:command")
        message = messages[-1]

        ce = message.to_cloudevent()
        restored = Message.from_cloudevent(ce)

        assert (
            restored.metadata.domain.correlation_id
            == message.metadata.domain.correlation_id
        )

    def test_checksum_preserved(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()
        restored = Message.from_cloudevent(ce)

        assert restored.metadata.envelope.checksum == message.metadata.envelope.checksum

    def test_sequence_preserved(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()
        restored = Message.from_cloudevent(ce)

        assert (
            restored.metadata.domain.sequence_id == message.metadata.domain.sequence_id
        )

    def test_kind_preserved(self):
        message, _ = _make_event_message()
        ce = message.to_cloudevent()
        restored = Message.from_cloudevent(ce)

        assert restored.metadata.domain.kind == message.metadata.domain.kind

    def test_domain_object_round_trip(self):
        """Full round-trip: event → message → CE → message → domain object."""
        message, identifier = _make_event_message()
        ce = message.to_cloudevent()
        restored = Message.from_cloudevent(ce)

        # The restored message should have the same type string,
        # making to_domain_object() work for registered types
        domain_obj = restored.to_domain_object()
        assert domain_obj.id == identifier
        assert domain_obj.email == "john@example.com"
        assert domain_obj.name == "John Doe"


# ═══════════════════════════════════════════════════════════════════════
# Edge-case tests for full coverage
# ═══════════════════════════════════════════════════════════════════════


class TestDeriveSourceFallback:
    """_derive_source() fallback chain when current_domain is unavailable."""

    def test_source_from_stream_category(self):
        """When current_domain raises, derive from stream_category."""
        metadata = Metadata(
            headers=MessageHeaders(id="test", type="Test.Event.v1"),
            domain=DomainMeta(stream_category="myapp::User"),
        )
        message = Message(data={}, metadata=metadata)

        with patch("protean.utils.eventing.current_domain") as mock:
            type(mock).config = PropertyMock(side_effect=RuntimeError)
            result = message._derive_source()

        assert result == "urn:protean:myapp"

    def test_source_unknown_when_all_fallbacks_fail(self):
        """Last resort: urn:protean:unknown."""
        metadata = Metadata(
            headers=MessageHeaders(id="test", type="Test.Event.v1"),
        )
        message = Message(data={}, metadata=metadata)

        with patch("protean.utils.eventing.current_domain") as mock:
            type(mock).config = PropertyMock(side_effect=RuntimeError)
            result = message._derive_source()

        assert result == "urn:protean:unknown"

    def test_source_unknown_when_stream_category_has_empty_domain(self):
        """When stream_category splits but first part is empty, fall to unknown."""
        metadata = Metadata(
            headers=MessageHeaders(id="test", type="Test.Event.v1"),
            domain=DomainMeta(stream_category="::User"),
        )
        message = Message(data={}, metadata=metadata)

        with patch("protean.utils.eventing.current_domain") as mock:
            type(mock).config = PropertyMock(side_effect=RuntimeError)
            result = message._derive_source()

        assert result == "urn:protean:unknown"


class TestExtractSubjectEdgeCases:
    """_extract_subject() edge cases."""

    def test_returns_none_when_no_metadata(self):
        message = Message(data={})
        assert message._extract_subject() is None

    def test_returns_none_when_no_stream(self):
        metadata = Metadata(
            headers=MessageHeaders(id="test", type="Test.Event.v1"),
        )
        message = Message(data={}, metadata=metadata)
        assert message._extract_subject() is None

    def test_subject_from_fact_event_with_category(self):
        metadata = Metadata(
            headers=MessageHeaders(
                id="test",
                type="Test.FactEvent.v1",
                stream="test::user-fact-abc123",
            ),
            domain=DomainMeta(stream_category="test::user"),
        )
        message = Message(data={}, metadata=metadata)
        assert message._extract_subject() == "abc123"

    def test_subject_from_command_with_category(self):
        metadata = Metadata(
            headers=MessageHeaders(
                id="test",
                type="Test.Command.v1",
                stream="test::user:command-abc123",
            ),
            domain=DomainMeta(stream_category="test::user"),
        )
        message = Message(data={}, metadata=metadata)
        assert message._extract_subject() == "abc123"

    def test_subject_from_event_without_category(self):
        """Fallback parsing: regular event stream without stream_category."""
        metadata = Metadata(
            headers=MessageHeaders(
                id="test",
                type="Test.Event.v1",
                stream="test::user-abc123",
            ),
        )
        message = Message(data={}, metadata=metadata)
        assert message._extract_subject() == "abc123"

    def test_subject_from_fact_event_without_category(self):
        """Fallback parsing: fact event stream without stream_category."""
        metadata = Metadata(
            headers=MessageHeaders(
                id="test",
                type="Test.FactEvent.v1",
                stream="test::user-fact-abc123",
            ),
        )
        message = Message(data={}, metadata=metadata)
        assert message._extract_subject() == "abc123"

    def test_returns_none_when_stream_has_no_separator(self):
        """Stream with no '-' or ':command-' returns None."""
        metadata = Metadata(
            headers=MessageHeaders(
                id="test",
                type="Test.Event.v1",
                stream="plainstream",
            ),
        )
        message = Message(data={}, metadata=metadata)
        assert message._extract_subject() is None

    def test_event_prefix_mismatch_falls_to_fallback(self):
        """When stream doesn't match category prefix, fall to fallback parsing."""
        metadata = Metadata(
            headers=MessageHeaders(
                id="test",
                type="Test.Event.v1",
                stream="other::order-abc123",
            ),
            domain=DomainMeta(stream_category="test::user"),
        )
        message = Message(data={}, metadata=metadata)
        # Falls through all category-based checks to fallback
        assert message._extract_subject() == "abc123"


class TestToCloudeventBranches:
    """to_cloudevent() branch coverage for optional/missing metadata."""

    def test_traceparent_included_when_set(self):
        """When traceparent is set on headers, it appears as W3C string."""
        tp = TraceParent(
            trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
            parent_id="00f067aa0ba902b7",
            sampled=True,
        )
        metadata = Metadata(
            headers=MessageHeaders(
                id="test",
                type="Test.Event.v1",
                stream="test::user-abc123",
                time=datetime.now(timezone.utc),
                traceparent=tp,
            ),
            domain=DomainMeta(
                stream_category="test::user",
                kind="EVENT",
                sequence_id="1",
            ),
            envelope=MessageEnvelope(
                specversion="1.0",
                checksum="test-checksum",
            ),
        )
        message = Message(data={"key": "value"}, metadata=metadata)
        ce = message.to_cloudevent()

        assert (
            ce["traceparent"]
            == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        )

    def test_causation_id_included_when_set(self):
        """When causation_id is set, it appears as proteancausationid."""
        metadata = Metadata(
            headers=MessageHeaders(
                id="test",
                type="Test.Event.v1",
                stream="test::user-abc123",
                time=datetime.now(timezone.utc),
            ),
            domain=DomainMeta(
                stream_category="test::user",
                kind="EVENT",
                sequence_id="1",
                causation_id="cause-xyz",
            ),
            envelope=MessageEnvelope(
                specversion="1.0",
                checksum="test-checksum",
            ),
        )
        message = Message(data={"key": "value"}, metadata=metadata)
        ce = message.to_cloudevent()

        assert ce["proteancausationid"] == "cause-xyz"

    def test_no_time_when_headers_time_is_none(self):
        """When headers.time is None, 'time' key is omitted."""
        metadata = Metadata(
            headers=MessageHeaders(id="test", type="Test.Event.v1"),
            domain=DomainMeta(kind="EVENT"),
        )
        message = Message(data={}, metadata=metadata)
        ce = message.to_cloudevent()

        assert "time" not in ce

    def test_no_subject_when_stream_unavailable(self):
        """When stream is not set, 'subject' key is omitted."""
        metadata = Metadata(
            headers=MessageHeaders(id="test", type="Test.Event.v1"),
            domain=DomainMeta(kind="EVENT"),
        )
        message = Message(data={}, metadata=metadata)
        ce = message.to_cloudevent()

        assert "subject" not in ce

    def test_no_domain_extensions_when_domain_is_none(self):
        """When domain meta is None, protean extensions are omitted."""
        metadata = Metadata(
            headers=MessageHeaders(id="test", type="Test.Event.v1"),
        )
        message = Message(data={}, metadata=metadata)
        ce = message.to_cloudevent()

        assert "proteankind" not in ce
        assert "sequence" not in ce
        assert "proteancorrelationid" not in ce
        assert "proteancausationid" not in ce

    def test_no_checksum_when_envelope_has_none(self):
        """When envelope.checksum is empty, proteanchecksum is omitted."""
        metadata = Metadata(
            headers=MessageHeaders(id="test", type="Test.Event.v1"),
            envelope=MessageEnvelope(specversion="1.0", checksum=None),
        )
        message = Message(data={}, metadata=metadata)
        ce = message.to_cloudevent()

        assert "proteanchecksum" not in ce

    def test_kind_omitted_when_none(self):
        """When domain.kind is None, proteankind is omitted."""
        metadata = Metadata(
            headers=MessageHeaders(id="test", type="Test.Event.v1"),
            domain=DomainMeta(sequence_id="1"),
        )
        message = Message(data={}, metadata=metadata)
        ce = message.to_cloudevent()

        assert "proteankind" not in ce


class TestFromCloudeventTimeParsing:
    """from_cloudevent() time parsing edge cases."""

    def test_time_as_datetime_object(self):
        """When time is already a datetime, use it directly."""
        now = datetime(2026, 3, 2, 10, 30, tzinfo=timezone.utc)
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "time": now,
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.headers.time == now

    def test_time_as_iso_string(self):
        """When time is a string, parse it via fromisoformat."""
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "time": "2026-03-02T10:30:00+00:00",
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.headers.time == datetime(
            2026, 3, 2, 10, 30, tzinfo=timezone.utc
        )

    def test_time_as_non_standard_type_ignored(self):
        """When time is neither datetime nor string, it stays None."""
        ce = {
            "specversion": "1.0",
            "id": "evt-001",
            "type": "com.example.test",
            "source": "/test",
            "time": 1234567890,
            "data": {},
        }
        message = Message.from_cloudevent(ce)

        assert message.metadata.headers.time is None
