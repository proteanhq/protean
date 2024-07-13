import pytest

from protean import BaseEvent, BaseEventSourcedAggregate
from protean.fields import String
from protean.fields.basic import Identifier


class User(BaseEventSourcedAggregate):
    id = Identifier(identifier=True)
    email = String()
    name = String()


class UserLoggedIn(BaseEvent):
    user_id = Identifier(identifier=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User)
    test_domain.register(UserLoggedIn, part_of="User")


def test_event_does_not_have_stream_category_before_domain_init():
    assert isinstance(UserLoggedIn.meta_.part_of, str)


def test_event_has_stream_category_after_domain_init(test_domain):
    test_domain.init(traverse=False)

    assert UserLoggedIn.meta_.part_of == User
    assert UserLoggedIn.meta_.part_of.meta_.stream_category == "user"
