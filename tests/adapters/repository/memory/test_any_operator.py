from protean import BaseAggregate
from protean.fields import List
from protean.globals import current_domain


class User(BaseAggregate):
    emails = List()


def test_for_any_lookup(test_domain):
    test_domain.register(User)

    user_repo = current_domain.repository_for(User)

    user_repo.add(User(emails=["foo@example.com", "bar@example.com"]))
    user_repo.add(User(emails=["baz@example.com", "bar@example.com"]))
    user_repo.add(User(emails=["qux@example.com"]))

    # One result
    users = user_repo._dao.query.filter(emails__any=["foo@example.com"]).all().items
    assert len(users) == 1

    # Scalar value to `any`
    users = user_repo._dao.query.filter(emails__any="foo@example.com").all().items
    assert len(users) == 1

    # Multiple results
    users = user_repo._dao.query.filter(emails__any=["bar@example.com"]).all().items
    assert len(users) == 2

    # Multiple input values
    users = (
        user_repo._dao.query.filter(emails__any=["foo@example.com", "baz@example.com"])
        .all()
        .items
    )
    assert len(users) == 2

    # Single value in target list
    users = user_repo._dao.query.filter(emails__any=["qux@example.com"]).all().items
    assert len(users) == 1
