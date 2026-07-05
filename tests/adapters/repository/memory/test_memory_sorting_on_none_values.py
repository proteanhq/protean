import datetime

from protean.core.aggregate import BaseAggregate
from protean.fields import Date, Integer, String


class User(BaseAggregate):
    name: String()
    joined_on: Date()
    seq: Integer()


def test_for_sorting_without_nulls(test_domain):
    test_domain.register(User)

    user_repo = test_domain.repository_for(User)

    user_repo.add(User(name="John", seq=1))
    user_repo.add(User(name="Jane", seq=2))
    user_repo.add(User(name="Baby1", seq=3))
    user_repo.add(User(name="Baby2", seq=4))

    # Assert the full ordered sequence, ascending and descending, so a broken
    # ``-`` (descending) prefix cannot slip through by matching only ``.first``.
    ascending = [u.name for u in user_repo.query.order_by("seq").all().items]
    assert ascending == ["John", "Jane", "Baby1", "Baby2"]

    descending = [u.name for u in user_repo.query.order_by("-seq").all().items]
    assert descending == ["Baby2", "Baby1", "Jane", "John"]


def test_for_sorting_with_dates(test_domain):
    test_domain.register(User)

    user_repo = test_domain.repository_for(User)

    today = datetime.date.today()

    user_repo.add(User(name="John"))
    user_repo.add(User(name="Jane"))
    user_repo.add(User(name="Baby1", joined_on=today))
    user_repo.add(User(name="Baby2", joined_on=(today - datetime.timedelta(days=1))))

    assert user_repo.query.order_by("joined_on").all().first.name == "Baby2"
    assert user_repo.query.order_by("joined_on").all().last.name == "Jane"
    assert user_repo.query.order_by("-joined_on").all().first.name == "John"
    assert user_repo.query.order_by("-joined_on").all().last.name == "Baby2"


def test_for_in_lookup_with_integers(test_domain):
    test_domain.register(User)

    user_repo = test_domain.repository_for(User)

    user_repo.add(User(name="John"))
    user_repo.add(User(name="Jane"))
    user_repo.add(User(name="Baby1", seq=2))
    user_repo.add(User(name="Baby2", seq=1))

    assert user_repo.query.order_by("seq").all().first.name == "Baby2"
    assert user_repo.query.order_by("-seq").all().first.name == "John"
    assert user_repo.query.order_by("-seq").all().last.name == "Baby2"
