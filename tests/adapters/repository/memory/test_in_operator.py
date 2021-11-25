from protean import BaseAggregate
from protean.fields.basic import String
from protean.globals import current_domain


class User(BaseAggregate):
    email = String()


def test_for_in_lookup(test_domain):
    test_domain.register(User)

    user_repo = current_domain.repository_for(User)

    user_repo.add(User(email="foo@example.com"))
    user_repo.add(User(email="baz@example.com"))
    user_repo.add(User(email="qux@example.com"))

    users = user_repo._dao.query.filter(email__in=["foo@example.com"]).all().items
    assert len(users) == 1

    users = (
        user_repo._dao.query.filter(email__in=["foo@example.com", "baz@example.com"])
        .all()
        .items
    )
    assert len(users) == 2

    users = user_repo._dao.query.filter(email__in="qux@example.com").all().items
    assert len(users) == 1
