from protean import BaseAggregate, BaseEvent
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseAggregate):
    email = String()
    name = String()


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


def test_stream_category_from_part_of(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn, part_of=User)

    assert UserLoggedIn.meta_.part_of.meta_.stream_category == "user"


def test_stream_category_from_explicit_stream_category_in_aggregate(test_domain):
    test_domain.register(User, stream_category="authentication")
    test_domain.register(UserLoggedIn, part_of=User)

    assert UserLoggedIn.meta_.part_of.meta_.stream_category == "authentication"
