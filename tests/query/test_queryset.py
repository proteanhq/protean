""" Test the Q object used for managing filter criteria """
import pytest

from protean.core.queryset import QuerySet
from protean.utils.query import Q

from .elements import Person


class TestCriteriaConstruction:
    """Test Conjunction operations on QuerySet"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)

    def test_that_an_empty_Q_object_is_initialized_with_queryset(self, test_domain):
        assert isinstance(test_domain.get_dao(Person).query, QuerySet)
        assert isinstance(test_domain.get_dao(Person).query._criteria, Q)

    def test_query_construction_with_simple_filter_kwargs(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(last_name="John")
        assert q1._criteria is not None

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert decon_args == ()
        assert decon_kwargs == {"last_name": "John"}
        assert q1._criteria.connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_simple_exclude_kwargs(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.exclude(last_name="John")

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert decon_args == ()
        assert decon_kwargs == {"last_name": "John", "_negated": True}
        assert q1._criteria.connector == Q.AND
        assert q1._criteria.negated is True
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_multiple_filter_criteria(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(last_name="John")
        q2 = q1.filter(age=3)

        _, decon_args, decon_kwargs = q2._criteria.deconstruct()

        assert decon_args == (("last_name", "John"), ("age", 3))
        assert decon_kwargs == {}
        assert q1._criteria.connector == Q.AND
        assert q2._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q2._criteria

    def test_query_construction_with_multiple_exclude_criteria(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.exclude(last_name="John")
        q2 = q1.exclude(age=3)

        _, decon_args, decon_kwargs = q2._criteria.deconstruct()

        assert str(decon_args) == (
            "(<Q: (NOT (AND: ('last_name', 'John')))>, " "<Q: (NOT (AND: ('age', 3)))>)"
        )
        assert decon_kwargs == {}
        assert q1._criteria.connector == Q.AND
        assert q2._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q2._criteria

    def test_query_construction_with_multiple_criteria_in_filter(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(last_name="John", age=3)
        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert decon_args == (("age", 3), ("last_name", "John"))
        assert decon_kwargs == {}
        assert q1._criteria.connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_multiple_criteria_in_exclude(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.exclude(last_name="John", age=3)

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert decon_args == (("age", 3), ("last_name", "John"))
        assert decon_kwargs == {"_negated": True}
        assert q1._criteria.connector == Q.AND
        assert q1._criteria.negated is True
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_combined_filter_and_exclude_with_filter_coming_first(
        self, test_domain
    ):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(last_name="John").exclude(age=3)

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert (
            str(decon_args) == "(('last_name', 'John'), <Q: (NOT (AND: ('age', 3)))>)"
        )
        assert decon_kwargs == {}
        assert q1._criteria.connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_combined_filter_and_exclude_with_exclude_coming_first(
        self, test_domain
    ):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.exclude(age=3).filter(last_name="John")

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert (
            str(decon_args) == "(<Q: (NOT (AND: ('age', 3)))>, ('last_name', 'John'))"
        )
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_single_Q_object_input_to_filter_method(
        self, test_domain
    ):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(Q(last_name="John"))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (AND: ('last_name', 'John'))>,)"
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_single_Q_object_to_exclude_method(
        self, test_domain
    ):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.exclude(Q(last_name="John"))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (AND: ('last_name', 'John'))>,)"
        assert decon_kwargs == {"_negated": True}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is True
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construnction_with_multiple_Q_objects_input_to_filter_method(
        self, test_domain
    ):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(Q(last_name="John"), Q(age=3))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert (
            str(decon_args)
            == "(<Q: (AND: ('last_name', 'John'))>, <Q: (AND: ('age', 3))>)"
        )
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construnction_with_multiple_Q_objects_input_to_exclude_method(
        self, test_domain
    ):
        q1 = test_domain.get_dao(Person).query.exclude(Q(last_name="John"), Q(age=3))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert (
            str(decon_args)
            == "(<Q: (AND: ('last_name', 'John'))>, <Q: (AND: ('age', 3))>)"
        )
        assert decon_kwargs == {"_negated": True}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is True
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_AND_filter(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(Q(last_name="John") & Q(age=3))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (AND: ('last_name', 'John'), ('age', 3))>,)"
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_OR_filter(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(Q(last_name="John") | Q(age=3))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (OR: ('last_name', 'John'), ('age', 3))>,)"
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.OR
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_multiple_AND_criteria(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(
            Q(last_name="John") & Q(age=3) & Q(name="Jean")
        )

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == (
            "(<Q: (AND: "
            "('last_name', 'John'), "
            "('age', 3), "
            "('name', 'Jean'))>,)"
        )
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_multiple_OR_criteria(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(
            Q(last_name="John") | Q(age=3) | Q(name="Jean")
        )

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == (
            "(<Q: (OR: " "('last_name', 'John'), " "('age', 3), " "('name', 'Jean'))>,)"
        )
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.OR
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_query_construction_with_AND_OR_combinations(self, test_domain):
        # Filter by the last_name
        q1 = test_domain.get_dao(Person).query.filter(
            Q(last_name="John") | Q(age=3), first_name="Jean"
        )
        _, decon_args, decon_kwargs = q1._criteria.deconstruct()
        assert str(decon_args) == (
            "(<Q: (OR: ('last_name', 'John'), ('age', 3))>, " "('first_name', 'Jean'))"
        )
        assert Q(*decon_args, **decon_kwargs) == q1._criteria
        assert q1._criteria.children[0].connector == Q.OR

        q2 = test_domain.get_dao(Person).query.filter(
            (Q(last_name="John") | Q(age=3)), Q(first_name="Jean")
        )
        _, decon_args, decon_kwargs = q2._criteria.deconstruct()
        assert str(decon_args) == (
            "(<Q: (OR: ('last_name', 'John'), ('age', 3))>, "
            "<Q: (AND: ('first_name', 'Jean'))>)"
        )
        assert Q(*decon_args, **decon_kwargs) == q2._criteria
        assert q2._criteria.children[0].connector == Q.OR

        q3 = test_domain.get_dao(Person).query.filter(
            Q(first_name="Jean") & (Q(last_name="John") | Q(age=3))
        )
        _, decon_args, decon_kwargs = q3._criteria.deconstruct()
        assert str(decon_args) == (
            "(<Q: (AND: "
            "('first_name', 'Jean'), "
            "(OR: ('last_name', 'John'), ('age', 3)))>,)"
        )
        assert Q(*decon_args, **decon_kwargs) == q3._criteria
        assert q3._criteria.children[0].connector == Q.AND

    def test_clone(self, test_domain):
        """Test that clone works as expected... it clones!"""
        query1 = test_domain.get_dao(Person).query.filter(last_name="John")
        query2 = query1.filter(age=3)
        query3 = query2.order_by("name")

        assert query1 != query2
        assert query2 != query3

    def test_list(self, test_domain):
        """Test that filter is evaluted on calling `list()`"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )
        dogs = list(query)

        assert dogs is not None
        assert len(dogs) == 2

    def test_repr(self, test_domain):
        """Test that filter is evaluted on calling `list()`"""
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )
        assert repr(query) == (
            "<QuerySet: entity: <class 'tests.query.elements.Person'>, "
            "criteria: ('protean.utils.query.Q', (), {'last_name': 'John'}), "
            "offset: 0, "
            "limit: 1000, order_by: ['age']>"
        )

    def test_bool_false(self, test_domain):
        """Test that `bool` returns `False` on no records"""
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )
        assert bool(query) is False

    def test_bool_true(self, test_domain):
        """Test that filter is evaluted on calling `list()`"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )

        # Filter by Dog attributes
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )

        assert bool(query) is True

    def test_len(self, test_domain):
        """Test that filter is evaluted on calling `list()`"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )
        assert len(query) == 2

    def test_slice(self, test_domain):
        """Test slicing on filter"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )
        test_domain.get_dao(Person).create(
            id=5, first_name="Fred", age=4, last_name="Constantine"
        )
        test_domain.get_dao(Person).create(
            id=6, first_name="Flint", age=2, last_name="Steve"
        )

        # Filter by Dog attributes
        query = test_domain.get_dao(Person).query.order_by("age")
        sliced = query[1:]
        assert len(sliced) == 4

    def test_caching(self, test_domain):
        """Test that results are cached after query is evaluated"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )

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
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )

        # Total invokes an evaluation and a query
        assert query.total == 2
        assert query._result_cache.total == 2

        query_dup = query.limit(25)
        assert query_dup._result_cache is None

    def test_total(self, test_domain):
        """Test value of `total` results"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )
        assert query.total == 2

    def test_total_with_cache(self, test_domain):
        """Test value of `total` results without refresh"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )
        assert query.total == 2

        test_domain.get_dao(Person).create(
            id=5, first_name="Berry", age=1, last_name="John"
        )
        assert query.total == 2
        assert query._result_cache.total == 2

        # Force a refresh
        assert query.all().total == 3

        # Result cache is now populated
        assert query._result_cache.total == 3

    def test_items(self, test_domain):
        """Test that items is retrieved from ResultSet"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )
        assert query.items[0].id == query.all().items[0].id

    def test_items_with_cache(self, test_domain):
        """Test that items is retrieved from ResultSet"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = (
            test_domain.get_dao(Person).query.filter(last_name="John").order_by("age")
        )
        assert query.items[0].id == 3

        test_domain.get_dao(Person).create(
            id=5, first_name="Berry", age=1, last_name="John"
        )
        assert query.items[0].id == 3

        assert query.all().items[0].id == 5

    def test_has_next(self, test_domain):
        """Test if there are results after the current set"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = test_domain.get_dao(Person).query.limit(2)
        assert query.has_next is True

    def test_has_next_with_cache(self, test_domain):
        """Test if there are results after the current set"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        dog = test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = test_domain.get_dao(Person).query.limit(2)
        assert query.has_next is True

        test_domain.get_dao(Person).delete(dog)

        assert query.has_next is True
        assert query.all().has_next is False

    def test_has_prev(self, test_domain):
        """Test if there are results before the current set"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = test_domain.get_dao(Person).query.offset(2).limit(2)
        assert query.has_prev is True

    def test_has_prev_with_cache(self, test_domain):
        """Test if there are results before the current set"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        dog = test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = test_domain.get_dao(Person).query.offset(2).limit(2)
        assert query.has_prev is True

        test_domain.get_dao(Person).delete(dog)

        assert query.has_prev is True
        assert query.all().has_prev is False

    def test_first(self, test_domain):
        """Test that the first item is retrieved correctly from the resultset"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = test_domain.get_dao(Person).query.order_by("-age")
        assert query.first.id == 2

    def test_first_with_cache(self, test_domain):
        """Test that the first item is retrieved correctly from the resultset"""
        # Add multiple entries to the DB
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        query = test_domain.get_dao(Person).query.order_by("-age")
        assert query.first.id == 2

        test_domain.get_dao(Person).create(
            id=5, first_name="Berry", age=8, last_name="John"
        )
        assert query.first.id == 2
        assert query.all().first.id == 5

    def test_raw(self, test_domain):
        """Test raw queries"""
        test_domain.get_dao(Person).create(
            id=2, first_name="Murdock", age=7, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=3, first_name="Jean", age=3, last_name="John"
        )
        test_domain.get_dao(Person).create(
            id=4, first_name="Bart", age=6, last_name="Carrie"
        )

        # Filter by Dog attributes
        results = test_domain.get_dao(Person).query.raw('{"last_name":"John"}')
        assert results.total == 2

        results = test_domain.get_dao(Person).query.raw("{'last_name':'John'}")
        assert results.total == 2

        results = test_domain.get_dao(Person).query.raw('{"last_name":"John", "age":3}')
        assert results.total == 1

        results = test_domain.get_dao(Person).query.raw(
            '{"last_name":"John", "age__in":[6,7]}'
        )
        assert results.total == 1

        results = test_domain.get_dao(Person).query.raw(
            '{"last_name":"John", "age__in":[3,7]}'
        )
        assert results.total == 2
