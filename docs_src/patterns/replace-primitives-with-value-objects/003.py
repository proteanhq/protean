from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, String, ValueObject

domain = Domain(name="EmailValueObject")


# --8<-- [start:email]
@domain.value_object
class Email:
    address: String(required=True, max_length=254)

    @invariant.post
    def must_be_valid_format(self):
        if not self.address or "@" not in self.address:
            raise ValidationError({"address": ["Must be a valid email address"]})

        local, _, domain_part = self.address.partition("@")
        if not local or not domain_part or "." not in domain_part:
            raise ValidationError({"address": ["Must be a valid email address"]})


@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    email = ValueObject(Email, required=True)


# --8<-- [end:email]


# --8<-- [start:usage]
def sign_up_valid_user():
    # Valid
    return User(email=Email(address="user@example.com"))


def sign_up_invalid_user():
    # Invalid: raises ValidationError at Email construction
    return User(email=Email(address="not-an-email"))


# --8<-- [end:usage]


# --8<-- [start:immutable]
def change_email():
    email = Email(address="user@example.com")
    email.address = "other@example.com"  # Raises IncorrectUsageError


# --8<-- [end:immutable]

domain.init(traverse=False)
