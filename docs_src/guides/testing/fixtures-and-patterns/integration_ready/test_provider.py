# --8<-- [start:provider_check]
import os

from myapp import domain
from myapp.models import User


def test_the_provider_follows_test_db():
    provider = domain.providers["default"].conn_info["provider"]
    assert provider == os.environ.get("TEST_DB", "memory")


# --8<-- [end:provider_check]


# Each test starts by checking the store is empty, so whichever runs second
# fails if data leaked from the first.
def test_a_user_round_trips():
    repo = domain.repository_for(User)
    assert repo.query.all().total == 0
    user = User(name="Alice")
    repo.add(user)
    assert repo.get(user.id).name == "Alice"


def test_another_user_round_trips():
    repo = domain.repository_for(User)
    assert repo.query.all().total == 0
    user = User(name="Bob")
    repo.add(user)
    assert repo.get(user.id).name == "Bob"
