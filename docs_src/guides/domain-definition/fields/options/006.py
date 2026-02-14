from protean import Domain
from pydantic import Field

domain = Domain()


@domain.aggregate
class Person:
    name: str
    email: str | None = Field(default=None, json_schema_extra={"unique": True})
