from pydantic import Field

from protean.core.projection import BaseProjection


class Person(BaseProjection):
    person_id: str = Field(json_schema_extra={"identifier": True})
    first_name: str
    last_name: str | None = None
    age: int = 21
