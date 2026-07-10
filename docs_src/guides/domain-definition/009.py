# --8<-- [start:full]
from protean.domain import Domain
from protean.exceptions import ValidationError
from protean.fields import String, ValueObject

domain = Domain(__name__)


class EmailValidator:
    def __init__(self):
        self.error = "Invalid email address"

    def __call__(self, value):
        """Business rules of Email address"""
        if (
            # should contain one "@" symbol
            value.count("@") != 1
            or value.startswith(("@", "."))
            or value.endswith(("@", "."))
            or value in ["..", ".@", "@."]
            or len(value.split("@")[0]) > 64
            or any(len(label) > 63 for label in value.split("@")[1].split("."))
            or not all(
                label[0].isalnum()
                and label[-1].isalnum()
                and all(c.isalnum() or c == "-" for c in label)
                for label in value.split("@")[1].split(".")
            )
            or not all(c.isprintable() and not c.isspace() for c in value)
        ):
            raise ValidationError(self.error)


@domain.value_object
class Email:
    """An email address value object, with two identified parts:
    * local_part
    * domain_part
    """

    # This is the external facing data attribute
    address: String(max_length=254, required=True, validators=[EmailValidator()])


@domain.aggregate
class User:
    email = ValueObject(Email)
    name: String(max_length=30)
    timezone: String(max_length=30)


# --8<-- [end:full]
