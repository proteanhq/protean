from unittest import mock

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.exceptions import ExpectedVersionError
from protean.fields import Identifier, String
from protean.utils.globals import current_uow


class Registered(BaseEvent):
    id: Identifier()
    email: String()
    name: String()


class User(BaseAggregate):
    id: Identifier(identifier=True)
    email: String()
    name: String()

    @apply
    def on_registered(self, event: Registered):
        self.id = event.id
        self.email = event.email
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(User, event_sourced=True)
    test_domain.register(Registered, part_of=User)
    test_domain.init(traverse=False)


@mock.patch("protean.core.repository.UnitOfWork.start")
@mock.patch("protean.core.repository.UnitOfWork.commit")
def test_that_method_is_enclosed_in_uow(mock_commit, mock_start, test_domain):
    mock_parent = mock.Mock()

    mock_parent.attach_mock(mock_start, "m1")
    mock_parent.attach_mock(mock_commit, "m2")

    with test_domain.domain_context():
        user = User(id=1, email="john.doe@example.com", name="John Doe")
        user.raise_(Registered(id=1, email="john.doe@example.com", name="John Doe"))
        test_domain.repository_for(User).add(user)

    mock_parent.assert_has_calls(
        [
            mock.call.m1(),
            mock.call.m2(),
        ]
    )


def test_a_failed_standalone_add_rolls_back_its_unit_of_work(test_domain):
    """A standalone ``add`` whose commit fails leaves no Unit of Work in
    progress."""
    repo = test_domain.repository_for(User)
    user = User(id="1", email="john.doe@example.com", name="John Doe")
    user.raise_(Registered(id="1", email="john.doe@example.com", name="John Doe"))
    repo.add(user)

    stale = User(id="1", email="john.doe@example.com", name="John Doe")
    stale.raise_(Registered(id="1", email="jane@example.com", name="Jane"))
    with pytest.raises(ExpectedVersionError):
        repo.add(stale)

    assert not (current_uow and current_uow.in_progress)
