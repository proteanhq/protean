from datetime import UTC, datetime

from protean import Domain
from protean.fields import DateTime, String, Text

domain = Domain(name="ChoosingElementsBlog")


# --8<-- [start:post]
@domain.aggregate
class Post:
    title: String(max_length=200, required=True)
    content: Text()
    author_id: String(required=True)
    published_at: DateTime()
    status: String(choices=["draft", "published"], default="draft")


# --8<-- [end:post]


# --8<-- [start:comment]
@domain.entity(part_of=Post)
class Comment:
    content: String(max_length=500, required=True)
    author_id: String(required=True)
    created_at: DateTime(default=lambda: datetime.now(UTC))


# --8<-- [end:comment]


# --8<-- [start:email]
from protean import invariant
from protean.exceptions import ValidationError


@domain.value_object
class Email:
    address: String(max_length=255, required=True)

    @invariant.post
    def must_contain_an_at_sign(self):
        if "@" not in self.address:
            raise ValidationError({"address": ["Invalid email format"]})


# --8<-- [end:email]
