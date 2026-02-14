from protean.domain import Domain
from typing import Annotated
from pydantic import Field

domain = Domain(__name__)


def standard_topics():
    return ["Music", "Cinema", "Politics"]


@domain.aggregate
class Adult:
    name: Annotated[str, Field(max_length=255)] | None = None
    topics: list = standard_topics
