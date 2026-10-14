# --8<-- [start:tests]
from myapp import domain
from myapp.models import User


# Each test expects an empty store, so whichever runs second fails without
# the cleanup fixture.
def test_alice_is_saved():
    assert domain.repository_for(User).query.all().total == 0
    domain.repository_for(User).add(User(name="Alice"))
    assert domain.repository_for(User).query.all().total == 1


def test_bob_is_saved():
    assert domain.repository_for(User).query.all().total == 0
    domain.repository_for(User).add(User(name="Bob"))
    assert domain.repository_for(User).query.all().total == 1


# --8<-- [end:tests]
