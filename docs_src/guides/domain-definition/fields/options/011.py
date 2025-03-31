from protean import Domain
from protean.fields import Integer

domain = Domain(__file__)


@domain.aggregate
class Building:
    doors = Integer(
        required=True, error_messages={"required": "Every building needs some!"}
    )
