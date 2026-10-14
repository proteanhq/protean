# --8<-- [start:user]
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, String

domain = Domain(name="ValidationLayeringProblem")


@domain.aggregate
class User:
    user_id: Auto(identifier=True)
    email: String(required=True, max_length=254)
    role: String(required=True, choices=["admin", "member", "guest"])

    @invariant.post
    def email_must_be_valid(self):
        if self.email and "@" not in self.email:
            raise ValidationError({"email": ["Invalid email format"]})

    @invariant.post
    def admin_must_have_company_email(self):
        if self.role == "admin" and not self.email.endswith("@company.com"):
            raise ValidationError(
                {"email": ["Admins must use a company email address"]}
            )


# --8<-- [end:user]

domain.init(traverse=False)
