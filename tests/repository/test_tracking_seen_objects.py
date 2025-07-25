import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.fields import String


class User(BaseAggregate):
    name = String()


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)


def test_tracking_aggregate_on_add(test_domain):
    uow = UnitOfWork()
    uow.start()

    test_domain.repository_for(User).add(User(name="John Doe"))

    assert len(uow._identity_map) == 1


def test_tracking_aggregate_on_update(test_domain):
    test_domain.repository_for(User).add(User(id=12, name="John Doe"))

    user = test_domain.repository_for(User).get(12)

    uow = UnitOfWork()
    uow.start()

    user.name = "Name Changed"
    test_domain.repository_for(User).add(user)

    assert len(uow._identity_map) == 1
    identifier = next(iter(uow._identity_map["default"]))
    assert uow._identity_map["default"][identifier].name == "Name Changed"


def test_tracking_aggregate_on_get(test_domain):
    test_domain.repository_for(User).add(User(id=12, name="John Doe"))

    uow = UnitOfWork()
    uow.start()

    test_domain.repository_for(User).get(12)

    assert len(uow._identity_map) == 1
    identifier = next(iter(uow._identity_map["default"]))
    assert isinstance(uow._identity_map["default"][identifier], User)


def test_tracking_aggregate_on_filtering(test_domain):
    test_domain.repository_for(User).add(User(id=12, name="John Doe"))
    test_domain.repository_for(User).add(User(id=13, name="Jane Doe"))

    uow = UnitOfWork()
    uow.start()

    test_domain.repository_for(User)._dao.query.filter(name__contains="Doe").all()

    assert len(uow._identity_map["default"]) == 2
    assert all(
        isinstance(item, User) for _, item in uow._identity_map["default"].items()
    )
