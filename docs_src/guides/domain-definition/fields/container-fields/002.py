from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class UserEvent:
    name: Annotated[str, Field(max_length=255)] | None = None
    payload: dict | None = None
