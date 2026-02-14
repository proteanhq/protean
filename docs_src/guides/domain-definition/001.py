from protean.domain import Domain
from protean.fields import Date, String

publishing = Domain()


@publishing.aggregate
class Post:
    name: String(max_length=50)
    created_on: Date()
