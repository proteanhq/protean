""" Test cases for the queryset class of entity"""
# Protean
from tests.old.support.dog import Dog


class TestQuerySet:
    """Class that holds Tests for QuerySet"""

    def test_clone(self, test_domain):
        """Test that clone works as expected... it clones!"""
        query1 = test_domain.get_repository(Dog).query.filter(owner='John')
        query2 = query1.filter(age=3)
        query3 = query2.order_by('name')

        assert query1 != query2
        assert query2 != query3

    def test_list(self, test_domain):
        """Test that filter is evaluted on calling `list()`"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')
        dogs = list(query)

        assert dogs is not None
        assert len(dogs) == 2

    def test_repr(self, test_domain):
        """Test that filter is evaluted on calling `list()`"""
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')
        assert repr(query) == ("<QuerySet: entity: <class 'tests.old.support.dog.Dog'>, "
                               "criteria: ('protean.utils.query.Q', (), {'owner': 'John'}), "
                               "offset: 0, "
                               "limit: 10, order_by: {'age'}>")

    def test_bool_false(self, test_domain):
        """Test that `bool` returns `False` on no records"""
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')
        assert bool(query) is False

    def test_bool_true(self, test_domain):
        """Test that filter is evaluted on calling `list()`"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')

        assert bool(query) is True

    def test_len(self, test_domain):
        """Test that filter is evaluted on calling `list()`"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')
        assert len(query) == 2

    def test_slice(self, test_domain):
        """Test slicing on filter"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')
        test_domain.get_repository(Dog).create(id=5, name='Fred', age=4, owner='Constantine')
        test_domain.get_repository(Dog).create(id=6, name='Flint', age=2, owner='Steve')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.order_by('age')
        sliced = query[1:]
        assert len(sliced) == 4

    def test_caching(self, test_domain):
        """Test that results are cached after query is evaluated"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')

        # Result cache is empty to begin with
        assert query._result_cache is None

        # Total invokes an evaluation and a query
        assert query.total == 2

        # Result cache is now populated
        assert query._result_cache is not None
        assert query._result_cache.total == 2

    def test_cache_reset(self, test_domain):
        """Test that results are cached after query is evaluated"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')

        # Total invokes an evaluation and a query
        assert query.total == 2
        assert query._result_cache.total == 2

        query_dup = query.limit(25)
        assert query_dup._result_cache is None

    def test_total(self, test_domain):
        """Test value of `total` results"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')
        assert query.total == 2

    def test_total_with_cache(self, test_domain):
        """Test value of `total` results without refresh"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')
        assert query.total == 2

        test_domain.get_repository(Dog).create(id=5, name='Berry', age=1, owner='John')
        assert query.total == 2
        assert query._result_cache.total == 2

        # Force a refresh
        assert query.all().total == 3

        # Result cache is now populated
        assert query._result_cache.total == 3

    def test_items(self, test_domain):
        """Test that items is retrieved from ResultSet"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')
        assert query.items[0].id == query.all().items[0].id

    def test_items_with_cache(self, test_domain):
        """Test that items is retrieved from ResultSet"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')
        assert query.items[0].id == 3

        test_domain.get_repository(Dog).create(id=5, name='Berry', age=1, owner='John')
        assert query.items[0].id == 3

        assert query.all().items[0].id == 5

    def test_has_next(self, test_domain):
        """Test if there are results after the current set"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.limit(2)
        assert query.has_next is True

    def test_has_next_with_cache(self, test_domain):
        """Test if there are results after the current set"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        dog = test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.limit(2)
        assert query.has_next is True

        test_domain.get_repository(Dog).delete(dog)

        assert query.has_next is True
        assert query.all().has_next is False

    def test_has_prev(self, test_domain):
        """Test if there are results before the current set"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.offset(2).limit(2)
        assert query.has_prev is True

    def test_has_prev_with_cache(self, test_domain):
        """Test if there are results before the current set"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        dog = test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.offset(2).limit(2)
        assert query.has_prev is True

        test_domain.get_repository(Dog).delete(dog)

        assert query.has_prev is True
        assert query.all().has_prev is False

    def test_first(self, test_domain):
        """Test that the first item is retrieved correctly from the resultset"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.order_by('-age')
        assert query.first.id == 2

    def test_first_with_cache(self, test_domain):
        """Test that the first item is retrieved correctly from the resultset"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.order_by('-age')
        assert query.first.id == 2

        test_domain.get_repository(Dog).create(id=5, name='Berry', age=8, owner='John')
        assert query.first.id == 2
        assert query.all().first.id == 5

    def test_raw(self, test_domain):
        """Test raw queries"""
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        results = test_domain.get_repository(Dog).query.raw('{"owner":"John"}')
        assert results.total == 2

        results = test_domain.get_repository(Dog).query.raw("{'owner':'John'}")
        assert results.total == 2

        results = test_domain.get_repository(Dog).query.raw('{"owner":"John", "age":3}')
        assert results.total == 1

        results = test_domain.get_repository(Dog).query.raw('{"owner":"John", "age__in":[6,7]}')
        assert results.total == 1

        results = test_domain.get_repository(Dog).query.raw('{"owner":"John", "age__in":[3,7]}')
        assert results.total == 2