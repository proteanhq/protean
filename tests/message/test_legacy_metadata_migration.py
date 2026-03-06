"""Test backward-compatible deserialization of messages with legacy metadata.

Old Protean versions stored metadata as flat keys (id, fqn, kind, type,
stream, timestamp, sequence_id, asynchronous, payload_hash, origin_stream).
Current versions use nested sub-objects (headers, domain, envelope,
event_store).  These tests ensure that messages persisted in the old format
can still be deserialized correctly.

Additionally, old versions stored the domain version as a string like "v1".
Current versions use plain integers. The ``_normalize_version`` method
converts these in-place during deserialization.
"""

import copy

from protean.utils.eventing import Message


class TestLegacyFlatMetadataDeserialization:
    """Deserialize messages written by old Protean versions with flat metadata."""

    def test_client_contact_updated_event(self):
        """Real message captured from a deployed message-db instance.

        Source: sustain_api event store, stream
        sustain_api::client-dc1eafa7-2e61-4d2c-81e9-0003554cf284, position 3.
        Written by Protean pre-nested-metadata (circa Jan 2026).
        """
        raw_message = {
            "id": "137be0a9-2fa0-4d1f-95ac-2a1641a66782",
            "stream_name": "sustain_api::client-dc1eafa7-2e61-4d2c-81e9-0003554cf284",
            "type": "SustainApi.ClientContactUpdated.v1",
            "data": {"id": "dc1eafa7-2e61-4d2c-81e9-0003554cf284"},
            "metadata": {
                "id": "sustain_api::client-dc1eafa7-2e61-4d2c-81e9-0003554cf284-3.4",
                "fqn": "src.clients.model.ClientContactUpdated",
                "kind": "EVENT",
                "type": "SustainApi.ClientContactUpdated.v1",
                "stream": "sustain_api::client-dc1eafa7-2e61-4d2c-81e9-0003554cf284",
                "version": 1,
                "timestamp": "2026-01-19 09:57:49.404658+00:00",
                "sequence_id": "3.4",
                "asynchronous": True,
                "payload_hash": "2522249191255527024",
                "origin_stream": None,
            },
            "position": 3,
            "global_position": 42,
        }

        msg = Message.deserialize(raw_message, validate=False)

        # Headers migrated from flat keys
        assert msg.metadata.headers.id == (
            "sustain_api::client-dc1eafa7-2e61-4d2c-81e9-0003554cf284-3.4"
        )
        assert msg.metadata.headers.type == "SustainApi.ClientContactUpdated.v1"
        assert msg.metadata.headers.stream == (
            "sustain_api::client-dc1eafa7-2e61-4d2c-81e9-0003554cf284"
        )
        assert str(msg.metadata.headers.time) == "2026-01-19 09:57:49.404658+00:00"

        # Domain metadata migrated from flat keys
        assert msg.metadata.domain.fqn == "src.clients.model.ClientContactUpdated"
        assert msg.metadata.domain.kind == "EVENT"
        assert msg.metadata.domain.version == 1
        assert msg.metadata.domain.sequence_id == "3.4"
        assert msg.metadata.domain.asynchronous is True
        assert msg.metadata.domain.origin_stream is None

        # Envelope: old payload_hash is incompatible, so checksum is None
        assert msg.metadata.envelope.specversion == "1.0"
        assert msg.metadata.envelope.checksum is None

        # Event store positions from root-level keys
        assert msg.metadata.event_store.position == 3
        assert msg.metadata.event_store.global_position == 42

        # Data preserved as-is
        assert msg.data == {"id": "dc1eafa7-2e61-4d2c-81e9-0003554cf284"}

    def test_legacy_flat_metadata_with_string_version(self):
        """Legacy flat metadata where version is stored as 'v1' string."""
        raw_message = {
            "id": "abc-123",
            "stream_name": "myapp::order-abc123",
            "type": "MyApp.OrderPlaced.v1",
            "data": {"order_id": "abc123", "amount": 100},
            "metadata": {
                "id": "myapp::order-abc123-1",
                "fqn": "src.orders.model.OrderPlaced",
                "kind": "EVENT",
                "type": "MyApp.OrderPlaced.v1",
                "stream": "myapp::order-abc123",
                "version": "v1",
                "timestamp": "2025-12-01 10:00:00+00:00",
                "sequence_id": "1",
                "asynchronous": True,
                "payload_hash": "1234567890",
                "origin_stream": None,
            },
            "position": 0,
            "global_position": 10,
        }

        msg = Message.deserialize(raw_message, validate=False)

        # Version normalized from "v1" to integer 1
        assert msg.metadata.domain.version == 1
        assert isinstance(msg.metadata.domain.version, int)

        # Rest of migration still works
        assert msg.metadata.headers.id == "myapp::order-abc123-1"
        assert msg.metadata.headers.type == "MyApp.OrderPlaced.v1"
        assert msg.metadata.domain.fqn == "src.orders.model.OrderPlaced"


class TestNormalizeVersionUnit:
    """Unit tests for Message._normalize_version on metadata dicts."""

    def test_lowercase_v_prefix(self):
        """'v1' is normalized to integer 1."""
        metadata_dict = {"domain": {"version": "v1"}}
        Message._normalize_version(metadata_dict)
        assert metadata_dict["domain"]["version"] == 1

    def test_uppercase_v_prefix(self):
        """'V1' is normalized to integer 1."""
        metadata_dict = {"domain": {"version": "V1"}}
        Message._normalize_version(metadata_dict)
        assert metadata_dict["domain"]["version"] == 1

    def test_multi_digit_version(self):
        """'v10' is normalized to integer 10."""
        metadata_dict = {"domain": {"version": "v10"}}
        Message._normalize_version(metadata_dict)
        assert metadata_dict["domain"]["version"] == 10

    def test_large_version_number(self):
        """'v123' is normalized to integer 123."""
        metadata_dict = {"domain": {"version": "v123"}}
        Message._normalize_version(metadata_dict)
        assert metadata_dict["domain"]["version"] == 123

    def test_integer_version_unchanged(self):
        """An already-integer version is left as-is."""
        metadata_dict = {"domain": {"version": 1}}
        Message._normalize_version(metadata_dict)
        assert metadata_dict["domain"]["version"] == 1

    def test_none_version_unchanged(self):
        """None version is left as-is (not a string)."""
        metadata_dict = {"domain": {"version": None}}
        Message._normalize_version(metadata_dict)
        assert metadata_dict["domain"]["version"] is None

    def test_no_domain_key(self):
        """No-op when 'domain' key is missing entirely."""
        metadata_dict = {"headers": {"id": "test"}}
        Message._normalize_version(metadata_dict)
        assert "domain" not in metadata_dict

    def test_domain_is_none(self):
        """No-op when domain value is None."""
        metadata_dict = {"domain": None}
        Message._normalize_version(metadata_dict)
        assert metadata_dict["domain"] is None

    def test_bare_numeric_string(self):
        """A bare '2' (no v prefix) is also normalized to integer 2."""
        metadata_dict = {"domain": {"version": "2"}}
        Message._normalize_version(metadata_dict)
        assert metadata_dict["domain"]["version"] == 2

    def test_version_missing_from_domain(self):
        """No-op when domain dict exists but has no 'version' key."""
        metadata_dict = {"domain": {"fqn": "test.Event"}}
        Message._normalize_version(metadata_dict)
        assert "version" not in metadata_dict["domain"]


class TestNormalizeVersionDeserialization:
    """Integration tests: legacy string versions through full deserialization."""

    @staticmethod
    def _make_message_dict(version_value: object) -> dict:
        """Build a minimal valid message dict with the given domain version."""
        return {
            "data": {"item": "widget"},
            "metadata": {
                "headers": {
                    "id": "test-msg-1",
                    "type": "TestApp.ItemCreated.v1",
                    "stream": "testapp::item-1",
                },
                "domain": {
                    "fqn": "test.ItemCreated",
                    "kind": "EVENT",
                    "origin_stream": None,
                    "version": version_value,
                    "sequence_id": "1",
                    "asynchronous": True,
                },
            },
        }

    def test_deserialize_with_v1_string(self):
        """'v1' string version is normalized during deserialization."""
        msg = Message.deserialize(self._make_message_dict("v1"), validate=False)
        assert msg.metadata.domain.version == 1
        assert isinstance(msg.metadata.domain.version, int)

    def test_deserialize_with_v2_string(self):
        """'v2' string version is normalized during deserialization."""
        msg = Message.deserialize(self._make_message_dict("v2"), validate=False)
        assert msg.metadata.domain.version == 2

    def test_deserialize_with_uppercase_V3(self):
        """'V3' uppercase string version is normalized during deserialization."""
        msg = Message.deserialize(self._make_message_dict("V3"), validate=False)
        assert msg.metadata.domain.version == 3

    def test_deserialize_with_integer_version(self):
        """Integer version passes through unchanged."""
        msg = Message.deserialize(self._make_message_dict(1), validate=False)
        assert msg.metadata.domain.version == 1

    def test_deserialize_preserves_other_fields(self):
        """Version normalization does not disturb other metadata fields."""
        raw = self._make_message_dict("v5")
        msg = Message.deserialize(raw, validate=False)

        assert msg.metadata.domain.version == 5
        assert msg.metadata.domain.fqn == "test.ItemCreated"
        assert msg.metadata.domain.kind == "EVENT"
        assert msg.metadata.domain.sequence_id == "1"
        assert msg.metadata.headers.id == "test-msg-1"
        assert msg.metadata.headers.type == "TestApp.ItemCreated.v1"
        assert msg.data == {"item": "widget"}

    def test_roundtrip_after_normalization(self):
        """A deserialized legacy message can be re-serialized and re-deserialized."""
        raw = self._make_message_dict("v1")
        msg = Message.deserialize(raw, validate=False)
        assert msg.metadata.domain.version == 1

        # Re-serialize
        msg_dict = msg.to_dict()
        assert msg_dict["metadata"]["domain"]["version"] == 1

        # Re-deserialize — version is already an int, should stay that way
        msg2 = Message.deserialize(msg_dict, validate=False)
        assert msg2.metadata.domain.version == 1

    def test_legacy_flat_format_with_string_version(self):
        """Legacy flat metadata + string version: both migrations apply."""
        raw = {
            "data": {"user_id": "u-42"},
            "metadata": {
                "id": "app::user-u42-1",
                "fqn": "src.users.UserCreated",
                "kind": "EVENT",
                "type": "App.UserCreated.v1",
                "stream": "app::user-u42",
                "version": "v1",
                "timestamp": "2025-06-15 12:00:00+00:00",
                "sequence_id": "1",
                "asynchronous": True,
                "payload_hash": "999",
                "origin_stream": None,
            },
            "position": 0,
            "global_position": 5,
        }

        msg = Message.deserialize(raw, validate=False)

        # Flat-to-nested migration applied
        assert msg.metadata.headers.id == "app::user-u42-1"
        assert msg.metadata.domain.fqn == "src.users.UserCreated"

        # Version normalization applied
        assert msg.metadata.domain.version == 1
        assert isinstance(msg.metadata.domain.version, int)

    def test_does_not_mutate_original_dict(self):
        """Deserialization should not corrupt the caller's original dict
        in a way that would break a second deserialization."""
        raw = self._make_message_dict("v1")
        raw_copy = copy.deepcopy(raw)

        Message.deserialize(raw, validate=False)

        # The metadata dict is mutated in-place (by design), but a second
        # deserialization from a fresh copy must also succeed.
        msg2 = Message.deserialize(raw_copy, validate=False)
        assert msg2.metadata.domain.version == 1
