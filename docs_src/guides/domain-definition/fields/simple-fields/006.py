from datetime import datetime, timezone

from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Post:
    title: Annotated[str, Field(max_length=255)] | None = None
    created_at: datetime = lambda: datetime.now(timezone.utc)
