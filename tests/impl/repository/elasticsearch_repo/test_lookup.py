from protean.impl.repository.elasticsearch_repo import Exact


class TestLookup:
    def test_exact_lookup(self, test_domain):
        lookup = Exact('first_name', 'John')

        assert lookup.as_expression() == {'filter': [{'term': {'first_name': 'John'}}]}
