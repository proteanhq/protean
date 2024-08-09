from unittest.mock import MagicMock

from protean.fields import Text


class TestFieldClone:
    def test_clone_basic_field(self):
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
        cloned_field = field._clone()

        # Assert
        assert cloned_field is not field, "The cloned field should be a new instance"
        assert cloned_field.referenced_as == field.referenced_as
        assert cloned_field.description == field.description
        assert cloned_field.identifier == field.identifier
        assert cloned_field.default == field.default
        assert cloned_field.required == field.required
        assert cloned_field.unique == field.unique
        assert cloned_field.choices == field.choices
        assert cloned_field.validators == field.validators
        assert cloned_field.error_messages == field.error_messages

    def test_clone_with_choices(self):
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
        cloned_field = field._clone()

        # Assert
        assert cloned_field is not field, "The cloned field should be a new instance"
        assert (
            cloned_field.choices == field.choices
        ), "Choices should be identical in the clone"

    def test_clone_with_validators(self):
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
        cloned_field = field._clone()

        # Assert
        assert cloned_field is not field, "The cloned field should be a new instance"
        assert (
            cloned_field.validators == field.validators
        ), "Validators should be identical in the clone"

    def test_clone_with_default_callable(self):
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
        cloned_field = field._clone()

        # Assert
        assert cloned_field is not field, "The cloned field should be a new instance"
        assert (
            cloned_field.default is field.default
        ), "Default callable should be identical in the clone"
