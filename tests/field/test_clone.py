"""Test FieldSpec copying/cloning behavior.

FieldSpec objects are plain data carriers that can be shallow-copied.
"""

import copy
from unittest.mock import MagicMock

from protean.fields import Text


class TestFieldSpecCopy:
    def test_copy_basic_fieldspec(self):
        # Arrange
        field = Text(
            referenced_as="test_field",
            description="Test Text",
            identifier=True,
            default="default_value",
            required=True,
            unique=True,
            choices=None,
            validators=[],
            error_messages={"invalid": "Invalid value"},
        )

        # Act
        cloned = copy.copy(field)

        # Assert
        assert cloned is not field, "The copied field should be a new instance"
        assert cloned.referenced_as == field.referenced_as
        assert cloned.description == field.description
        assert cloned.identifier == field.identifier
        assert cloned.default == field.default
        assert cloned.required == field.required
        assert cloned.unique == field.unique
        assert cloned.choices == field.choices
        assert cloned.validators == field.validators
        assert cloned.error_messages == field.error_messages

    def test_copy_with_choices(self):
        # Arrange
        choices_mock = MagicMock()
        field = Text(
            referenced_as="test_field",
            description="Test Text",
            identifier=False,
            default=None,
            required=False,
            unique=False,
            choices=choices_mock,
            validators=[],
            error_messages={"invalid_choice": "Invalid choice"},
        )

        # Act
        cloned = copy.copy(field)

        # Assert
        assert cloned is not field, "The copied field should be a new instance"
        assert cloned.choices == field.choices, (
            "Choices should be identical in the copy"
        )

    def test_copy_with_validators(self):
        # Arrange
        validators = [lambda x: x > 0]
        field = Text(
            referenced_as="test_field",
            description="Test Text",
            identifier=False,
            default=None,
            required=False,
            unique=False,
            choices=None,
            validators=validators,
            error_messages={"required": "This field is required"},
        )

        # Act
        cloned = copy.copy(field)

        # Assert
        assert cloned is not field, "The copied field should be a new instance"
        assert cloned.validators == field.validators, (
            "Validators should be identical in the copy"
        )

    def test_copy_with_default_callable(self):
        # Arrange
        field = Text(
            referenced_as="test_field",
            description="Test Text",
            identifier=False,
            default=lambda: "dynamic_default",
            required=False,
            unique=False,
            choices=None,
            validators=[],
            error_messages={"invalid": "Invalid value"},
        )

        # Act
        cloned = copy.copy(field)

        # Assert
        assert cloned is not field, "The copied field should be a new instance"
        assert cloned.default is field.default, (
            "Default callable should be identical in the copy"
        )
