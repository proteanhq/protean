""" Test cases for the queryset class of entity"""
from tests.support.dog import Dog


class TestQuerySet:
    """Class that holds Tests for QuerySet"""

    def test_clone(self):
        """Test that clone works as expected... it clones!"""
        query1 = Dog.query.filter(owner='John')
        query2 = query1.filter(age=3)
        query3 = query2.order_by('name')

        assert query1 != query2
        assert query2 != query3

    def test_list(self):
        """Test that filter is evaluted on calling `list()`"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')
        dogs = list(query)

        assert dogs is not None
        assert len(dogs) == 2

    def test_repr(self):
        """Test that filter is evaluted on calling `list()`"""
        query = Dog.query.filter(owner='John').order_by('age')
        assert repr(query) == ("<QuerySet: entity: <class 'tests.support.dog.Dog'>, "
                               "criteria: ('protean.utils.query.Q', (), {'owner': 'John'}), "
                               "page: 1, "
                               "per_page: 10, order_by: {'age'}>")

    def test_bool_false(self):
        """Test that `bool` returns `False` on no records"""
        query = Dog.query.filter(owner='John').order_by('age')
        assert bool(query) is False

    def test_bool_true(self):
        """Test that filter is evaluted on calling `list()`"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')

        assert bool(query) is True

    def test_len(self):
        """Test that filter is evaluted on calling `list()`"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')
        assert len(query) == 2

    def test_slice(self):
        """Test slicing on filter"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')
        Dog.create(id=5, name='Fred', age=4, owner='Constantine')
        Dog.create(id=6, name='Flint', age=2, owner='Steve')

        # Filter by Dog attributes
        query = Dog.query.order_by('age')
        sliced = query[1:]
        assert len(sliced) == 4

    def test_caching(self):
        """Test that results are cached after query is evaluated"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')

        # Result cache is empty to begin with
        assert query._result_cache is None

        # Total invokes an evaluation and a query
        assert query.total == 2

        # Result cache is now populated
        assert query._result_cache is not None
        assert query._result_cache.total == 2

    def test_cache_reset(self):
        """Test that results are cached after query is evaluated"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')

        # Total invokes an evaluation and a query
        assert query.total == 2
        assert query._result_cache.total == 2

        query_dup = query.paginate(per_page=25)
        assert query_dup._result_cache is None

    def test_total(self):
        """Test value of `total` results"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')
        assert query.total == 2

    def test_total_with_cache(self):
        """Test value of `total` results without refresh"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')
        assert query.total == 2

        Dog.create(id=5, name='Berry', age=1, owner='John')
        assert query.total == 2
        assert query._result_cache.total == 2

        # Force a refresh
        assert query.all().total == 3

        # Result cache is now populated
        assert query._result_cache.total == 3

    def test_items(self):
        """Test that items is retrieved from Pagination results"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')
        assert query.items[0].id == query.all().items[0].id

    def test_items_with_cache(self):
        """Test that items is retrieved from Pagination results"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')
        assert query.items[0].id == 3

        Dog.create(id=5, name='Berry', age=1, owner='John')
        assert query.items[0].id == 3

        assert query.all().items[0].id == 5

    def test_has_next(self):
        """Test if there are results after the current set"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.paginate(page=1, per_page=2)
        assert query.has_next is True

    def test_has_next_with_cache(self):
        """Test if there are results after the current set"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        dog = Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.paginate(page=1, per_page=2)
        assert query.has_next is True

        dog.delete()

        assert query.has_next is True
        assert query.all().has_next is False

    def test_has_prev(self):
        """Test if there are results before the current set"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.paginate(page=2, per_page=2)
        assert query.has_prev is True

    def test_has_prev_with_cache(self):
        """Test if there are results before the current set"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        dog = Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.paginate(page=2, per_page=2)
        assert query.has_prev is True

        dog.delete()

        assert query.has_prev is True
        assert query.all().has_prev is False

    def test_first(self):
        """Test that the first item is retrieved correctly from the resultset"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.order_by('-age')
        assert query.first.id == 2

    def test_first_with_cache(self):
        """Test that the first item is retrieved correctly from the resultset"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.order_by('-age')
        assert query.first.id == 2

        Dog.create(id=5, name='Berry', age=8, owner='John')
        assert query.first.id == 2
        assert query.all().first.id == 5
