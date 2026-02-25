import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import String


class User(BaseAggregate):
    name: String(required=True)
    email: String(required=True)


@pytest.fixture
def user_cls():
    """Provide the User class to tests, ensuring class identity
    matches what is registered in the db fixture."""
    return User


@pytest.fixture
def db(test_domain):
    """Override root db fixture to register User before creating
    database artifacts, ensuring the index exists for ES tests."""
    test_domain.register(User)
    test_domain.init(traverse=False)

    test_domain.providers["default"]._create_database_artifacts()

    yield

    test_domain.providers["default"]._drop_database_artifacts()
    test_domain.registry._reset()
