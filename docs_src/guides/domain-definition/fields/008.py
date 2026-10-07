# --8<-- [start:aggregate]
from protean import Domain
from protean.fields import HasMany, String

domain = Domain(name="Publishing")


@domain.aggregate
class Post:
    title: String(max_length=200, required=True)
    comments = HasMany("Comment")


@domain.entity(part_of=Post)
class Comment:
    content: String(max_length=500)


# --8<-- [end:aggregate]
