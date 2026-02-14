from protean import Domain
from pydantic import Field

domain = Domain()


@domain.aggregate
class Person:
    email: str | None = Field(default=None, json_schema_extra={"unique": True})
    name: str = Field(json_schema_extra={"referenced_as": "fullname"})
