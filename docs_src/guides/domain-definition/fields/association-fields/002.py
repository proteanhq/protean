from protean import Domain
from protean.fields import HasMany, Float, String, Text

domain = Domain(__file__, load_toml=False)


@domain.aggregate
class Post:
    title = String(required=True, max_length=100)
    body = Text()
    comments = HasMany("Comment")


@domain.entity(part_of=Post)
class Comment:
    content = String(required=True, max_length=50)
    rating = Float(max_value=5)
