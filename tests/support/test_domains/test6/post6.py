from datetime import datetime

from protean.fields import DateTime, HasMany, Reference, String
from tests.support.test_domains.test6.publishing6 import domain


@domain.aggregate
class Post:
    title = String(max_length=50)
    created_on = DateTime(default=datetime.now)

    comments = HasMany("Comment")


@domain.entity(part_of=Post)
class Comment:
    content = String(max_length=500)
    post = Reference(Post)
