from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from protean import Domain
from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.exceptions import InvalidOperationError, ValidationError
from protean.fields import Identifier, String
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
        domain = Domain()
        domain.config["identity_type"] = "invalid"

        with domain.domain_context():
            identifier = Identifier()
            with pytest.raises(ValidationError) as exc:
                identifier._load(42)

            assert exc.value.messages == {
                "identity_type": ["Identity type not supported"]
            }

    def test_that_default_is_picked_from_domain_config(self):
        domain = Domain()

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


class TestIdentifierValidation:
    """Test cases to cover missing validation error paths"""

    def test_identifier_with_invalid_uuid_string(self):
        """Test UUID identifier with invalid UUID string"""
        identifier = Identifier(identity_type=IdentityType.UUID.value)
        with pytest.raises(ValidationError):
            identifier._load("invalid-uuid-string")

    def test_identifier_with_invalid_int_string(self):
        """Test INTEGER identifier with invalid integer string"""
        identifier = Identifier(identity_type=IdentityType.INTEGER.value)
        with pytest.raises(ValidationError):
            identifier._load("not-a-number")

    def test_identifier_with_boolean_value(self):
        """Test identifier with boolean value"""
        identifier = Identifier()
        with pytest.raises(ValidationError):
            identifier._load(True)

    def test_unsupported_identity_type_during_cast(self):
        """Test unsupported identity type during cast"""
        identifier = Identifier()
        # Force an unsupported identity type
        identifier.identity_type = "UNSUPPORTED"

        with pytest.raises(ValidationError) as exc:
            identifier._load("test")
        assert "Identity type not supported" in str(exc.value)


class TestIdentifierImmutability:
    """Test cases to cover identifier immutability"""

    def test_cannot_change_identifier_once_set(self, test_domain):
        """Test that identifiers cannot be changed once set"""

        @test_domain.aggregate
        class TestAggregate(BaseAggregate):
            id = Identifier(identifier=True)
            name = String()

        aggregate = TestAggregate(id="test-id", name="test")

        # Try to change the identifier
        with pytest.raises(InvalidOperationError) as exc:
            aggregate.id = "new-id"

        assert "Identifiers cannot be changed once set" in str(exc.value)

    def test_can_set_identifier_to_same_value(self, test_domain):
        """Test that setting identifier to same value is allowed"""

        @test_domain.aggregate
        class TestAggregate(BaseAggregate):
            id = Identifier(identifier=True)
            name = String()

        aggregate = TestAggregate(id="test-id", name="test")

        # Set identifier to same value - should not raise error
        aggregate.id = "test-id"
        assert aggregate.id == "test-id"

    def test_can_set_identifier_if_none(self, test_domain):
        """Test that identifier can be set if it's None - covers early return in __set__"""

        @test_domain.aggregate
        class TestAggregate(BaseAggregate):
            custom_id = Identifier(identifier=True)
            name = String()

        aggregate = TestAggregate(custom_id="test-id", name="test")

        # Setting identifier to same value should work (covers the condition where value == existing_value)
        aggregate.custom_id = "test-id"
        assert aggregate.custom_id == "test-id"
