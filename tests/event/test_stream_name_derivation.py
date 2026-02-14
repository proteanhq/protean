from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None


class UserLoggedIn(BaseEvent):
    user_id: str = Field(json_schema_extra={"identifier": True})


def test_stream_category_from_part_of(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn, part_of=User)

    assert UserLoggedIn.meta_.part_of.meta_.stream_category == "test::user"


def test_stream_category_from_explicit_stream_category_in_aggregate(test_domain):
    test_domain.register(User, stream_category="authentication")
    test_domain.register(UserLoggedIn, part_of=User)

    assert UserLoggedIn.meta_.part_of.meta_.stream_category == "test::authentication"
