from protean.core.aggregate import BaseAggregate


class User(BaseAggregate):
    email: str
    password: str | None = None


def test_memory_dao_repr(test_domain):
    dao = test_domain.repository_for(User)._dao
    assert str(dao) == "DictDAO <User>"
