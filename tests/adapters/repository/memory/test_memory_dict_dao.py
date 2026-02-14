from protean.core.aggregate import BaseAggregate
from protean.fields import String


class User(BaseAggregate):
    email: String(max_length=255, required=True, unique=True)
    password: String(max_length=3026)


def test_memory_dao_repr(test_domain):
    dao = test_domain.repository_for(User)._dao
    assert str(dao) == "DictDAO <User>"
