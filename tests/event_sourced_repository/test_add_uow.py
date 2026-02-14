import mock
import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None


class Registered(BaseEvent):
    id: str | None = None
    email: str | None = None
    name: str | None = None


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, is_event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


@mock.patch("protean.core.repository.UnitOfWork.start")
@mock.patch("protean.core.repository.UnitOfWork.commit")
def test_that_method_is_enclosed_in_uow(mock_commit, mock_start, test_domain):
    mock_parent = mock.Mock()

    mock_parent.attach_mock(mock_start, "m1")
    mock_parent.attach_mock(mock_commit, "m2")

    with test_domain.domain_context():
        user = User(id="1", email="john.doe@example.com", name="John Doe")
        user.raise_(Registered(id="1", email="john.doe@example.com", name="John Doe"))
        test_domain.repository_for(User).add(user)

    mock_parent.assert_has_calls(
        [
            mock.call.m1(),
            mock.call.m2(),
        ]
    )
