from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String


class Person(BaseAggregate):
    name: String(max_length=255)
    age: Integer()


class TestQueryLimitProperty:
    def test_query_limit_property(self, test_domain):
        test_domain.register(Person)
        person_repo = test_domain.repository_for(Person)
        assert person_repo._dao.query._limit == 100

    def test_cloning_with_explicit_limit(self, test_domain):
        test_domain.register(Person)
        person_repo = test_domain.repository_for(Person)
        query = person_repo._dao.query.limit(500)
        assert query._limit == 500

    def test_cloning_and_removing_limit(self, test_domain):
        test_domain.register(Person)
        person_repo = test_domain.repository_for(Person)
        query = person_repo._dao.query.limit(500)
        assert query._limit == 500
        query = query.limit(None)
        assert query._limit is None

    def test_cloning_with_invalid_limit_value(self, test_domain):
        test_domain.register(Person)
        person_repo = test_domain.repository_for(Person)
        query = person_repo._dao.query.limit("invalid")
        assert query._limit == 100
