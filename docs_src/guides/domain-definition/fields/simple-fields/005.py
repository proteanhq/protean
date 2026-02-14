from datetime import datetime, date

from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


@domain.aggregate
class Post:
    title: Annotated[str, Field(max_length=255)] | None = None
    published_on: date = lambda: datetime.today().date()
