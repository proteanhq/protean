import json

from protean.domain import Domain
from protean.fields import Date, String

publishing = Domain(__file__, name="Publishing", load_toml=False)


@publishing.aggregate
class Post:
    name = String(max_length=50)
    created_on = Date()


with publishing.domain_context():
    post = Post(name="My First Post", created_on="2024-01-01")
    print(json.dumps(post.to_dict(), indent=4))
