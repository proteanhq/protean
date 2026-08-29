from protean.domain import Domain
from protean.fields.simple import String

domain = Domain(name="TEST_DRAIN")


@domain.aggregate
class Widget:
    name = String(max_length=50, required=True)
