from protean import Domain
from protean.fields import HasOne, Integer, String

domain = Domain(name="Publishing")


# --8<-- [start:dict]
@domain.aggregate
class Post:
    title: String(max_length=100)
    stats = HasOne("Statistic")


@domain.entity(part_of=Post)
class Statistic:
    likes: Integer()
    dislikes: Integer()


domain.init(traverse=False)

with domain.domain_context():
    post = Post(title="My Post")
    post.stats = {"likes": 10, "dislikes": 1}
    # Equivalent to: post.stats = Statistic(likes=10, dislikes=1)
# --8<-- [end:dict]
