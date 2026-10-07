from protean import Domain
from protean.fields import Boolean, HasOne, String

domain = Domain(name="Blogging")


# --8<-- [start:aggregate]
@domain.aggregate
class Blog:
    title: String(max_length=100)
    settings = HasOne("BlogSettings")


@domain.entity(part_of=Blog)
class BlogSettings:
    theme: String(max_length=50)
    allow_comments: Boolean(default=True)


# --8<-- [end:aggregate]
