# --8<-- [start:tests]
from myapp import domain
from myapp.models import User, UserRegistered


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


def _register(name):
    user = User(name=name, email=f"{name.lower()}@example.com")
    user.raise_(UserRegistered(user_id=user.id, email=user.email, name=name))
    domain.repository_for(User).add(user)


# The same pair for the event store: whichever runs second finds the other
# test's event unless the cleanup fixture resets the store.
def test_alice_registration_is_stored():
    assert list(domain.event_store.store.read_all()) == []
    _register("Alice")
    assert len(list(domain.event_store.store.read_all())) == 1


def test_bob_registration_is_stored():
    assert list(domain.event_store.store.read_all()) == []
    _register("Bob")
    assert len(list(domain.event_store.store.read_all())) == 1
