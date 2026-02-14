from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class User:
    email: Annotated[str, Field(max_length=255, json_schema_extra={"unique": True})]
    roles: list = []
