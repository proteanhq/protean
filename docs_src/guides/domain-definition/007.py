from protean.domain import Domain
from protean.fields import Date, String

publishing = Domain(__name__)


@publishing.aggregate
class Post:
    name = String(max_length=50)
    created_on = Date()


@publishing.entity(part_of=Post)
class Comment:
    content = String(max_length=500)
