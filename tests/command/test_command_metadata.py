from uuid import uuid4

import pytest

from protean import BaseAggregate, BaseCommand
from protean.fields import Identifier, String
from protean.reflection import fields


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
        assert hasattr(metadata_field.value_object_cls, "type")

    def test_command_metadata_type_default(self):
        assert hasattr(Login, "__type__")
        assert Login.__type__ == "Test.Login.v1"

    def test_type_value_in_metadata(self, test_domain):
        command = test_domain._enrich_command(Login(user_id=str(uuid4())))
        assert command._metadata.type == "Test.Login.v1"


class TestMetadataVersion:
    def test_metadata_has_command_version(self):
        metadata_field = fields(Login)["_metadata"]
        assert hasattr(metadata_field.value_object_cls, "version")

    def test_command_metadata_version_default(self):
        command = Login(user_id=str(uuid4()))
        assert command._metadata.version == "v1"

    def test_overridden_version(self, test_domain):
        class Login(BaseCommand):
            __version__ = "v2"
            user_id = Identifier(identifier=True)

        test_domain.register(Login, part_of=User)

        command = Login(user_id=str(uuid4()))
        assert command._metadata.version == "v2"
