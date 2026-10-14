from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, String, ValueObject

domain = Domain(name="ValidationOnValueObjects")


# --8<-- [start:value_objects]
@domain.value_object
class Email:
    address: String(required=True, max_length=254)

    @invariant.post
    def must_be_valid(self):
        if "@" not in self.address:
            raise ValidationError({"address": ["Invalid email"]})


@domain.value_object
class Phone:
    number: String(required=True, max_length=20)

    @invariant.post
    def must_be_valid(self):
        digits = self.number.replace("+", "").replace("-", "").replace(" ", "")
        if not digits.isdigit():
            raise ValidationError({"number": ["Invalid phone number"]})


@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    email = ValueObject(Email, required=True)
    phone = ValueObject(Phone)
    # No email or phone validation invariants needed on User


# --8<-- [end:value_objects]

domain.init(traverse=False)
