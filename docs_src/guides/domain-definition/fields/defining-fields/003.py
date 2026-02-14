from typing import Annotated

from pydantic import Field

from protean import Domain
from protean.fields import String

domain = Domain()


@domain.aggregate
class Metric:
    name: String(max_length=100, required=True)
    score: float = 0.0
    metadata: Annotated[dict, Field(default_factory=dict)]
