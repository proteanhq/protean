import datetime

from protean import BaseAggregate
from protean.fields import Date, Integer, String
from protean.globals import current_domain


class User(BaseAggregate):
    name = String()
    joined_on = Date()
    seq = Integer()


def test_for_sorting_without_nulls(test_domain):
    test_domain.register(User)

    user_repo = current_domain.repository_for(User)

    user_repo.add(User(name="John", seq=1))
    user_repo.add(User(name="Jane", seq=2))
    user_repo.add(User(name="Baby1", seq=3))
    user_repo.add(User(name="Baby2", seq=4))

    user_repo._dao.query.order_by("seq").all().first.name == "John"
    user_repo._dao.query.order_by("-seq").all().first.name == "Baby2"


def test_for_sorting_with_dates(test_domain):
    test_domain.register(User)

    user_repo = current_domain.repository_for(User)

    today = datetime.date.today()

    user_repo.add(User(name="John"))
    user_repo.add(User(name="Jane"))
    user_repo.add(User(name="Baby1", joined_on=today))
    user_repo.add(User(name="Baby2", joined_on=(today - datetime.timedelta(days=1))))

    assert user_repo._dao.query.order_by("joined_on").all().first.name == "Baby2"
    assert user_repo._dao.query.order_by("joined_on").all().last.name == "Jane"
    assert user_repo._dao.query.order_by("-joined_on").all().first.name == "John"
    assert user_repo._dao.query.order_by("-joined_on").all().last.name == "Baby2"


def test_for_in_lookup_with_integers(test_domain):
    test_domain.register(User)

    user_repo = current_domain.repository_for(User)

    user_repo.add(User(name="John"))
    user_repo.add(User(name="Jane"))
    user_repo.add(User(name="Baby1", seq=2))
    user_repo.add(User(name="Baby2", seq=1))

    assert user_repo._dao.query.order_by("seq").all().first.name == "Baby2"
    assert user_repo._dao.query.order_by("-seq").all().first.name == "John"
    assert user_repo._dao.query.order_by("-seq").all().last.name == "Baby2"
