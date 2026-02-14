from datetime import datetime, timezone

from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


def utc_now():
    return datetime.now(timezone.utc)


@domain.aggregate(abstract=True, auto_add_id_field=False)
class TimeStamped:
    created_at: datetime = utc_now
    updated_at: datetime = utc_now


@domain.aggregate
class User(TimeStamped):
    name: Annotated[str, Field(max_length=30)] | None = None
    timezone: Annotated[str, Field(max_length=30)] | None = None
