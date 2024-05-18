from protean import Domain
from protean.fields import HasMany, String, Text

domain = Domain(__file__)


@domain.aggregate
class Post:
    title = String(required=True, max_length=100)
    body = Text()
    comments = HasMany("Comment")


@domain.entity(part_of=Post)
class Comment:
    content = String(required=True, max_length=50)
