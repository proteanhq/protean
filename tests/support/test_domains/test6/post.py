from datetime import datetime

from protean.fields import DateTime, HasMany, Reference, String

from .publishing import domain


@domain.aggregate
class Post:
    title = String(max_length=50)
    created_on = DateTime(default=datetime.now)

    comments = HasMany("Comment")


@domain.entity(aggregate_cls=Post)
class Comment:
    content = String(max_length=500)
    post = Reference(Post)
