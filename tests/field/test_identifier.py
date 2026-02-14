"""Test Identifier field behavior through domain objects.

The Identifier factory function now returns a FieldSpec with
field_kind='identifier'. Identity type handling, UUID generation, etc.
are tested through actual aggregates/entities.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import InvalidOperationError
from protean.fields import Identifier, String
from protean.fields.spec import FieldSpec


class TestIdentifierFieldSpec:
    """Test the FieldSpec properties of Identifier fields."""

    def test_identifier_returns_fieldspec(self):
        identifier = Identifier()
        assert isinstance(identifier, FieldSpec)
        assert identifier.field_kind == "identifier"
        assert identifier.python_type is str

    def test_identifier_with_identifier_flag(self):
        identifier = Identifier(identifier=True)
        assert identifier.identifier is True


class TestIdentifierBehaviorThroughAggregates:
    """Test identifier behavior through actual aggregate instantiation."""

    def test_string_identifier_in_aggregate(self, test_domain):
        @test_domain.aggregate
        class TestAggregate(BaseAggregate):
            id = Identifier(identifier=True)
            name = String()

        aggregate = TestAggregate(id="test-42", name="test")
        assert aggregate.id == "test-42"
        assert isinstance(aggregate.id, str)

    def test_identifier_in_to_dict(self, test_domain):
        @test_domain.aggregate
        class TestAggregate(BaseAggregate):
            id = Identifier(identifier=True)
            name = String()

        aggregate = TestAggregate(id="test-42", name="test")
        result = aggregate.to_dict()
        assert result["id"] == "test-42"


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

        # Setting identifier to same value should work
        aggregate.custom_id = "test-id"
        assert aggregate.custom_id == "test-id"
