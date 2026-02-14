from protean import Domain
from uuid import uuid4
from pydantic import Field

domain = Domain()


@domain.aggregate
class User:
    user_id: str = Field(
        default_factory=lambda: str(uuid4()), json_schema_extra={"identifier": True}
    )
    name: str
