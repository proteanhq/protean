from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import String

domain = Domain(name="ValidationOnUser")


# --8<-- [start:user]
@domain.aggregate
class User:
    email: String(required=True)
    phone: String()

    @invariant.post
    def email_must_be_valid(self):
        # Email validation on the User aggregate
        if self.email and "@" not in self.email:
            raise ValidationError({"email": ["Invalid email"]})

    @invariant.post
    def phone_must_be_valid(self):
        # Phone validation on the User aggregate
        if self.phone and not self.phone.replace("+", "").replace("-", "").isdigit():
            raise ValidationError({"phone": ["Invalid phone number"]})


# --8<-- [end:user]

domain.init(traverse=False)
