from protean import Domain
from pydantic import Field

domain = Domain()


@domain.aggregate
class Person:
    email: str = Field(json_schema_extra={"identifier": True})
    name: str
