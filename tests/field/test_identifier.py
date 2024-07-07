from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import Identifier
from protean.utils import IdentityType


def test_UUID_identifiers_are_converted_into_strings_in_as_dict():
    uuid_val = uuid4()
    identifier = Identifier(identity_type=IdentityType.UUID.value)

    value = identifier._load(uuid_val)

    assert isinstance(value, UUID)
    assert identifier.as_dict(value) == str(uuid_val)


def test_int_identifiers_are_preserved_as_ints_in_as_dict():
    identifier = Identifier(identity_type=IdentityType.INTEGER.value)

    value = identifier._load(42)

    assert isinstance(value, int)
    assert identifier.as_dict(value) == 42


def test_string_identifiers_are_preserved_as_strings_in_as_dict():
    identifier = Identifier()

    value = identifier._load("42")

    assert isinstance(value, str)
    assert identifier.as_dict(value) == "42"


def test_that_only_ints_or_strings_are_allowed_in_identifiers():
    identifier = Identifier()

    invalid_values = [42.0, {"a": 1}, ["a", "b"], True, datetime.now(UTC)]
    for value in invalid_values:
        with pytest.raises(ValidationError):
            identifier._load(value)


class TestIdentityType:
    def test_with_identity_type_as_uuid(self):
        identifier = Identifier(identity_type=IdentityType.UUID.value)
        value = identifier._load(uuid4())

        assert isinstance(value, UUID)
        assert isinstance(identifier.as_dict(value), str)

    def test_with_identity_type_as_int(self):
        identifier = Identifier(identity_type=IdentityType.INTEGER.value)
        value = identifier._load(42)

        assert isinstance(value, int)
        assert identifier.as_dict(value) == 42

    def test_with_identity_type_as_string(self):
        identifier = Identifier(identity_type=IdentityType.STRING.value)
        value = identifier._load("42")

        assert isinstance(value, str)
        assert identifier.as_dict(value) == "42"

    def test_with_identity_type_as_invalid(self):
        with pytest.raises(ValidationError) as exc:
            Identifier(identity_type="invalid")

        assert exc.value.messages == {"identity_type": ["Identity type not supported"]}

    def test_with_invalid_value_for_uuid_identity_type(self):
        identifier = Identifier(identity_type=IdentityType.UUID.value)
        with pytest.raises(ValidationError):
            identifier._load(42)

        with pytest.raises(ValidationError):
            identifier._load("42")

    def test_with_string_value_for_uuid_identity_type(self):
        identifier = Identifier(identity_type=IdentityType.UUID.value)
        uuid_val = uuid4()
        assert identifier._load(str(uuid_val)) == uuid_val

    def test_with_invalid_value_for_int_identity_type(self):
        identifier = Identifier(identity_type=IdentityType.INTEGER.value)

        # With INTEGER, Strings that have valid integers or UUIDs should be allowed
        uuid_val = uuid4()
        assert identifier._load(uuid_val) == int(uuid_val)
        assert identifier._load("42") == 42

        with pytest.raises(ValidationError):
            identifier._load("ABC")

    def test_int_and_uuid_values_for_string_identity_type(self):
        identifier = Identifier(identity_type=IdentityType.STRING.value)

        # With STRING, a valid UUID will be allowed
        uuid_val = uuid4()
        assert identifier._load(uuid_val) == str(uuid_val)

        # With STRING, an INTEGER will be converted to a string
        identifier._load(42) == "42"

    def test_invalid_identity_type_in_domain_config(self):
        domain = Domain(__file__, load_toml=False)
        domain.config["identity_type"] = "invalid"

        with domain.domain_context():
            identifier = Identifier()
            with pytest.raises(ValidationError) as exc:
                identifier._load(42)

            assert exc.value.messages == {
                "identity_type": ["Identity type not supported"]
            }

    def test_that_default_is_picked_from_domain_config(self):
        domain = Domain(__file__, load_toml=False)

        # By default, IdentityType is UUID
        with domain.domain_context():
            uuid_val = uuid4()
            identifier = Identifier()

            # Can load UUIDs as Strings
            assert identifier._load(str(uuid_val)) == str(uuid_val)
            assert identifier.identity_type == IdentityType.STRING.value

            # Can load arbitrary strings as well
            assert identifier._load("42") == "42"
            assert identifier.as_dict("42") == "42"

        domain.config["identity_type"] = IdentityType.INTEGER.value
        with domain.domain_context():
            identifier = Identifier()
            assert identifier._load(42) == 42
            assert identifier.identity_type == IdentityType.INTEGER.value
            assert identifier.as_dict(42) == 42

        domain.config["identity_type"] = IdentityType.UUID.value
        with domain.domain_context():
            uuid_val = uuid4()
            identifier = Identifier()
            assert identifier._load(uuid_val) == uuid_val
            assert identifier.identity_type == IdentityType.UUID.value
            assert identifier.as_dict(uuid_val) == str(uuid_val)
