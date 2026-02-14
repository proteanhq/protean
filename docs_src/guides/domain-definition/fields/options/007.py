from enum import Enum

from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


class BuildingStatus(Enum):
    WIP = "WIP"
    DONE = "DONE"


@domain.aggregate
class Building:
    name: Annotated[str, Field(max_length=50)] | None = None
    floors: int | None = None
    status: BuildingStatus | None = None
