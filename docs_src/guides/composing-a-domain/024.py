import time

from protean import Domain
from pydantic import Field

domain = Domain()


def gen_id():  # (1)
    return int(time.time() * 1000)


@domain.aggregate
class User:
    user_id: str = Field(
        json_schema_extra={"identifier": True},
        identity_strategy="function",
        identity_function=gen_id,
        identity_type="integer",
    )
    name: str
