from protean.domain import Domain
from protean.fields import Date, String

publishing = Domain(__file__)


@publishing.aggregate
class Post:
    name = String(max_length=50)
    created_on = Date()
