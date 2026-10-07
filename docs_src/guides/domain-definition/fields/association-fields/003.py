from protean import Domain
from protean.fields import HasMany, Reference, String

domain = Domain(name="Blog")


# --8<-- [start:explicit_reference]
@domain.aggregate
class Post:
    title: String(max_length=100)
    comments = HasMany("Comment")


@domain.entity(part_of=Post)
class Comment:
    content: String(max_length=500)
    post = Reference(Post)  # Explicit reference field


# --8<-- [end:explicit_reference]
