from protean import Domain
from protean.fields import HasMany, String

domain = Domain(name="Publishing")


# --8<-- [start:aggregate]
@domain.aggregate
class Post:
    title: String(max_length=100)
    comments = HasMany("Comment")


@domain.entity(part_of=Post)
class Comment:
    content: String(max_length=500)
    author: String(max_length=50)


# --8<-- [end:aggregate]

# --8<-- [start:helpers]
domain.init(traverse=False)

with domain.domain_context():
    post = Post(title="New Post")

    # Add comments
    post.add_comments(Comment(content="First comment", author="alice"))
    post.add_comments(
        [
            Comment(content="Second comment", author="bob"),
            Comment(content="Third comment", author="alice"),
        ]
    )

    # Query within the collection
    alice_comments = post.filter_comments(author="alice")
    bob_comment = post.get_one_from_comments(author="bob")

    # Remove
    post.remove_comments(bob_comment)
# --8<-- [end:helpers]

# --8<-- [start:navigation]
with domain.domain_context():
    # From parent to child
    post = Post(title="My Post")
    post.add_comments(Comment(content="Great post!", author="alice"))
    comments = post.comments  # List of Comment objects

    # From child to parent
    comment = post.comments[0]
    post = comment.post  # Post object
    post_id = comment.post_id  # Post's ID value
# --8<-- [end:navigation]
