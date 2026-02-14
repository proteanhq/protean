from datetime import datetime, timezone

from protean.domain import Domain
from typing import Annotated
from pydantic import Field

publishing = Domain(__name__)


def utc_now():
    return datetime.now(timezone.utc)


@publishing.aggregate
class Post:
    title: Annotated[str, Field(max_length=50)] | None = None
    created_at: datetime = utc_now
