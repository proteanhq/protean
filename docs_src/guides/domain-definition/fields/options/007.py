from enum import Enum

from protean import Domain
from protean.fields import Integer, String

domain = Domain()


class BuildingStatus(Enum):
    WIP = "WIP"
    DONE = "DONE"


@domain.aggregate
class Building:
    name = String(max_length=50)
    floors = Integer()
    status = String(choices=BuildingStatus)
