import json

from protean.domain import Domain
from datetime import date
from typing import Annotated
from pydantic import Field

publishing = Domain(name="Publishing")


@publishing.aggregate
class Post:
    name: Annotated[str, Field(max_length=50)] | None = None
    created_on: date | None = None


with publishing.domain_context():
    post = Post(name="My First Post", created_on="2024-01-01")
    print(json.dumps(post.to_dict(), indent=4, default=str))
