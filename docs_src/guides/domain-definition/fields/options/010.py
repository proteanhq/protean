from typing import Any

from protean import Domain
from protean.exceptions import ValidationError
from pydantic import Field

domain = Domain()


class EmailDomainValidator:
    def __init__(self, domain="example.com"):
        self.domain = domain
        self.message = f"Email does not belong to {self.domain}"

    def __call__(self, value: str) -> Any:
        if not value.endswith(self.domain):
            raise ValidationError(self.message)


@domain.aggregate
class Employee:
    email: str = Field(
        json_schema_extra={
            "identifier": True,
            "validators": [EmailDomainValidator("mydomain.com")],
        }
    )
