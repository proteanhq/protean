from protean import Domain
from protean.fields import HasMany, Reference, String

domain = Domain(name="Publishing")


@domain.aggregate
class Post:
    title: String(max_length=100)
    comments = HasMany("Comment")


# --8<-- [start:entity]
@domain.entity(part_of=Post)
class Comment:
    content: String(max_length=500)
    author: String(max_length=50)
    post = Reference(Post)  # Explicit reference field


# --8<-- [end:entity]
