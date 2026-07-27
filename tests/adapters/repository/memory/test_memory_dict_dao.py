from protean.core.aggregate import BaseAggregate
from protean.fields import String


class User(BaseAggregate):
    email: String(max_length=255, required=True, unique=True)
    password: String(max_length=3026)


def test_memory_dao_repr(test_domain):
    dao = test_domain.repository_for(User)._dao
    assert str(dao) == "DictDAO <User>"


def test_delete_all_without_criteria_returns_deleted_count(test_domain):
    """``_delete_all()`` with no criteria returns the number of records removed,
    matching the SQLAlchemy and Elasticsearch adapters (it used to return 0)."""
    dao = test_domain.repository_for(User)._dao
    dao.create(email="a@example.com", password="x")
    dao.create(email="b@example.com", password="y")
    dao.create(email="c@example.com", password="z")

    deleted = dao._delete_all()

    assert deleted == 3
    assert dao.query.all().total == 0
