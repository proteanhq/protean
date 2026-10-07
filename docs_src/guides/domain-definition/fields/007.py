# --8<-- [start:aggregate]
from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import String

domain = Domain(name="Staffing")


class EmailDomainValidator:
    def __init__(self, allowed_domain: str):
        self.allowed_domain = allowed_domain

    def __call__(self, value: str) -> None:
        if not value.endswith(f"@{self.allowed_domain}"):
            raise ValidationError(f"Email does not belong to {self.allowed_domain}")


@domain.aggregate
class Employee:
    email: String(validators=[EmailDomainValidator("mydomain.com")])


# --8<-- [end:aggregate]
