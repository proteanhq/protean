from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, String

domain = Domain(name="EmailOnUser")


# --8<-- [start:user]
@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    email: String(required=True)

    @invariant.post
    def email_must_be_valid(self):
        if self.email and "@" not in self.email:
            raise ValidationError({"email": ["Invalid email address"]})


# --8<-- [end:user]

domain.init(traverse=False)
