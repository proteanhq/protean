"""A simple domain module with domain elements in the same file"""

from datetime import datetime

from protean.domain import Domain
from protean.fields import DateTime, HasMany, Reference, String

domain = Domain(__file__, "TEST9")


@domain.aggregate
class Post:
    title = String(max_length=50)
    created_on = DateTime(default=datetime.now)

    comments = HasMany("Comment")


@domain.entity(aggregate_cls=Post)
class Comment:
    content = String(max_length=500)
    post = Reference(Post)
