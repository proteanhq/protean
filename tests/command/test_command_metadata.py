from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.fields import Identifier, String
from protean.utils import Processing, fqn
from protean.utils.eventing import MessageEnvelope
from protean.utils.reflection import fields


class User(BaseAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class Login(BaseCommand):
    user_id = Identifier(identifier=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(Login, part_of=User)
    test_domain.init(traverse=False)


class TestMetadataType:
    def test_metadata_has_type_field(self):
        metadata_field = fields(Login)["_metadata"]
        assert hasattr(metadata_field.value_object_cls, "headers")

    def test_command_metadata_type_default(self):
        assert hasattr(Login, "__type__")
        assert Login.__type__ == "Test.Login.v1"

    def test_type_value_in_metadata(self, test_domain):
        command = test_domain._enrich_command(Login(user_id=str(uuid4())), True)
        assert command._metadata.headers.type == "Test.Login.v1"


class TestMetadataVersion:
    def test_metadata_has_command_version(self):
        metadata_field = fields(Login)["_metadata"]
        assert hasattr(metadata_field.value_object_cls, "domain")

    def test_command_metadata_version_default(self):
        command = Login(user_id=str(uuid4()))
        assert command._metadata.domain.version == "v1"

    def test_overridden_version(self, test_domain):
        class Login(BaseCommand):
            __version__ = "v2"
            user_id = Identifier(identifier=True)

        test_domain.register(Login, part_of=User)
        test_domain.init(traverse=False)

        command = Login(user_id=str(uuid4()))
        assert command._metadata.domain.version == "v2"


class TestMetadataAsynchronous:
    def test_metadata_has_asynchronous_field(self):
        metadata_field = fields(Login)["_metadata"]
        assert hasattr(metadata_field.value_object_cls, "domain")

    def test_command_metadata_asynchronous_default(self):
        command = Login(user_id=str(uuid4()))
        assert command._metadata.domain.asynchronous is True

    def test_command_metadata_asynchronous_override(self, test_domain):
        identifier = str(uuid4())
        command = Login(user_id=identifier)
        test_domain.process(command, asynchronous=False)

        last_command = test_domain.event_store.store.read_last_message(
            f"test::user:command-{identifier}"
        )
        assert last_command is not None
        assert last_command.metadata.domain.asynchronous is False

    def test_command_metadata_asynchronous_default_from_domain(self, test_domain):
        test_domain.config["command_processing"] = Processing.SYNC.value

        identifier = str(uuid4())
        command = Login(user_id=identifier)
        test_domain.process(command)

        last_command = test_domain.event_store.store.read_last_message(
            f"test::user:command-{identifier}"
        )
        assert last_command is not None
        assert last_command.metadata.domain.asynchronous is False


def test_command_metadata(test_domain):
    identifier = str(uuid4())
    command = test_domain._enrich_command(Login(user_id=identifier), True)

    # Compute expected checksum
    expected_checksum = MessageEnvelope.compute_checksum(command.payload)

    assert (
        command.to_dict()
        == {
            "_metadata": {
                "domain": {
                    "fqn": fqn(Login),
                    "kind": "COMMAND",
                    "origin_stream": None,
                    "stream_category": None,
                    "version": "v1",
                    "sequence_id": None,
                    "asynchronous": True,
                    "expected_version": None,
                },
                "envelope": {
                    "specversion": "1.0",
                    "checksum": expected_checksum,
                },
                "headers": {
                    "id": f"{identifier}",  # FIXME Double-check command identifier format and construction
                    "type": "Test.Login.v1",
                    "stream": f"test::user:command-{identifier}",
                    "time": str(command._metadata.headers.time),
                    "traceparent": None,
                },
                "event_store": None,
            },
            "user_id": command.user_id,
        }
    )


class TestCommandEnvelope:
    def test_enrich_command_adds_envelope_with_checksum(self, test_domain):
        """Test that _enrich_command adds envelope with correct checksum"""
        identifier = str(uuid4())
        command = Login(user_id=identifier)

        enriched_command = test_domain._enrich_command(command, True)

        # Verify envelope exists
        assert enriched_command._metadata.envelope is not None
        assert enriched_command._metadata.envelope.specversion == "1.0"

        # Verify checksum is computed correctly
        expected_checksum = MessageEnvelope.compute_checksum(enriched_command.payload)
        assert enriched_command._metadata.envelope.checksum == expected_checksum

    def test_command_envelope_checksum_changes_with_payload(self, test_domain):
        """Test that different payloads produce different checksums"""
        command1 = Login(user_id=str(uuid4()))
        command2 = Login(user_id=str(uuid4()))

        enriched1 = test_domain._enrich_command(command1, True)
        enriched2 = test_domain._enrich_command(command2, True)

        # Different payloads should have different checksums
        assert (
            enriched1._metadata.envelope.checksum
            != enriched2._metadata.envelope.checksum
        )

    def test_command_envelope_checksum_consistent_for_same_payload(self, test_domain):
        """Test that same payload always produces same checksum"""
        identifier = str(uuid4())
        command1 = Login(user_id=identifier)
        command2 = Login(user_id=identifier)

        enriched1 = test_domain._enrich_command(command1, True)
        enriched2 = test_domain._enrich_command(command2, True)

        # Same payload should have same checksum
        assert (
            enriched1._metadata.envelope.checksum
            == enriched2._metadata.envelope.checksum
        )
