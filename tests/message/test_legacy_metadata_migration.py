"""Test backward-compatible deserialization of messages with legacy flat metadata.

Old Protean versions stored metadata as flat keys (id, fqn, kind, type,
stream, timestamp, sequence_id, asynchronous, payload_hash, origin_stream).
Current versions use nested sub-objects (headers, domain, envelope,
event_store).  These tests ensure that messages persisted in the old format
can still be deserialized correctly.
"""

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
                "version": "v1",
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
        assert msg.metadata.domain.version == "v1"
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
