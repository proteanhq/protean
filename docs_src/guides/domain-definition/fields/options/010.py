from typing import Any

from protean import Domain
from protean.exceptions import ValidationError
from protean.fields import String

domain = Domain(__file__)


class EmailDomainValidator:
    def __init__(self, domain="example.com"):
        self.domain = domain
        self.message = f"Email does not belong to {self.domain}"

    def __call__(self, value: str) -> Any:
        if not value.endswith(self.domain):
            raise ValidationError(self.message)


@domain.aggregate
class Employee:
    email = String(identifier=True, validators=[EmailDomainValidator("mydomain.com")])
