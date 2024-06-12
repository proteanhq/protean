from protean import Domain
from protean.fields import Float, HasMany, String, Text

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


domain.init(traverse=False)
with domain.domain_context():
    post = Post(
        id="1",
        title="A Great Post",
        body="This is the body of a great post",
        comments=[
            Comment(id="1", content="Amazing!", rating=5.0),
            Comment(id="2", content="Great!", rating=4.5),
        ],
    )

    # This persists one `Post` record and two `Comment` records
    domain.repository_for(Post).add(post)
