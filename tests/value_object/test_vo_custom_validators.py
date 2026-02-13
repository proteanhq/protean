# FIXME Use the file at docs_src/guides/domain-definition/009.py
import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.value_object import _LegacyBaseValueObject as BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import String, ValueObject


class EmailValidator:
    def __init__(self):
        self.error = "Invalid email address"

    def __call__(self, value):
        """Business rules of Email address"""
        if (
            # should contain one "@" symbol
            value.count("@") != 1
            # should not start with "@" or "."
            or value.startswith("@")
            or value.startswith(".")
            # should not end with "@" or "."
            or value.endswith("@")
            or value.endswith(".")
            # should not contain consecutive dots
            or value in ["..", ".@", "@."]
            # local part should not be more than 64 characters
            or len(value.split("@")[0]) > 64
            # Each label can be up to 63 characters long.
            or any(len(label) > 63 for label in value.split("@")[1].split("."))
            # Labels must start and end with a letter (a-z, A-Z) or a digit (0-9), and can contain hyphens (-),
            # but cannot start or end with a hyphen.
            or not all(
                label[0].isalnum()
                and label[-1].isalnum()
                and all(c.isalnum() or c == "-" for c in label)
                for label in value.split("@")[1].split(".")
            )
            # No spaces or unprintable characters are allowed.
            or not all(c.isprintable() and not c.isspace() for c in value)
        ):
            raise ValidationError(self.error)


class Email(BaseValueObject):
    """An email address value object, with two identified parts:
    * local_part
    * domain_part
    """

    # This is the external facing data attribute
    address = String(max_length=254, required=True, validators=[EmailValidator()])


class User(BaseAggregate):
    email = ValueObject(Email)
    name = String(max_length=30)
    timezone = String(max_length=30)


def test_vo_with_correct_email_address():
    email = Email(address="john.doe@gmail.com")
    assert email.address == "john.doe@gmail.com"


def test_vo_with_incorrect_email_address():
    with pytest.raises(ValidationError) as exc:
        Email(address="john.doegmail.com")

    assert str(exc.value) == str({"address": ["Invalid email address"]})


def test_embedded_vo_with_correct_email_address():
    user = User(
        email_address="john.doe@gmail.com",
        name="John Doe",
        timezone="America/Los_Angeles",
    )
    assert user.email.address == "john.doe@gmail.com"


def test_embedded_vo_with_incorrect_email_address():
    with pytest.raises(ValidationError) as exc:
        User(
            email_address="john.doegmail.com",
            name="John Doe",
            timezone="America/Los_Angeles",
        )

    assert str(exc.value) == str({"email_address": ["Invalid email address"]})
