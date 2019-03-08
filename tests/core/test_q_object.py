""" Test the Q object used for managing filter criteria """
from tests.support.dog import Dog

from protean.core.entity import QuerySet
from protean.utils.query import Q


class TestCriteriaConstruction:
    """Test Conjunction operations on QuerySet"""

    def test_empty_query(self):
        """Test that an empty Q object is initialized with Queryset"""
        assert isinstance(Dog.query, QuerySet)
        assert isinstance(Dog.query._criteria, Q)

    def test_simple_filter(self):
        """Test query construction with simple filter kwargs"""
        # Filter by the Owner
        q1 = Dog.query.filter(owner='John')
        assert q1._criteria is not None

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert decon_args == ()
        assert decon_kwargs == {'owner': 'John'}
        assert q1._criteria.connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_simple_exclude(self):
        """Test query construction with simple exclude kwargs"""
        # Filter by the Owner
        q1 = Dog.query.exclude(owner='John')

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert decon_args == ()
        assert decon_kwargs == {'owner': 'John', '_negated': True}
        assert q1._criteria.connector == Q.AND
        assert q1._criteria.negated is True
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_multiple_filters(self):
        """Test query construction with multiple filter criteria"""
        # Filter by the Owner
        q1 = Dog.query.filter(owner='John')
        q2 = q1.filter(age=3)

        _, decon_args, decon_kwargs = q2._criteria.deconstruct()

        assert decon_args == (('owner', 'John'), ('age', 3))
        assert decon_kwargs == {}
        assert q1._criteria.connector == Q.AND
        assert q2._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q2._criteria

    def test_multiple_excludes(self):
        """Test query construction with multiple exclude criteria"""
        # Filter by the Owner
        q1 = Dog.query.exclude(owner='John')
        q2 = q1.exclude(age=3)

        _, decon_args, decon_kwargs = q2._criteria.deconstruct()

        assert str(decon_args) == ("(<Q: (NOT (AND: ('owner', 'John')))>, "
                                   "<Q: (NOT (AND: ('age', 3)))>)")
        assert decon_kwargs == {}
        assert q1._criteria.connector == Q.AND
        assert q2._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q2._criteria

    def test_multiple_criteria_in_filter(self):
        """Test query construction with multiple filter in filter"""
        # Filter by the Owner
        q1 = Dog.query.filter(owner='John', age=3)
        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert decon_args == (('age', 3), ('owner', 'John'))
        assert decon_kwargs == {}
        assert q1._criteria.connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_multiple_criteria_in_exclude(self):
        """Test query construction with multiple filter in exclude"""
        # Filter by the Owner
        q1 = Dog.query.exclude(owner='John', age=3)

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert decon_args == (('age', 3), ('owner', 'John'))
        assert decon_kwargs == {'_negated': True}
        assert q1._criteria.connector == Q.AND
        assert q1._criteria.negated is True
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_combined_filter_and_exclude(self):
        """Test query construction with combined filter/exclude with filter coming first"""
        # Filter by the Owner
        q1 = Dog.query.filter(owner='John').exclude(age=3)

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(('owner', 'John'), <Q: (NOT (AND: ('age', 3)))>)"
        assert decon_kwargs == {}
        assert q1._criteria.connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_combined_exclude_and_filter(self):
        """Test query construction with combined filter/exclude with exclude coming first"""
        # Filter by the Owner
        q1 = Dog.query.exclude(age=3).filter(owner='John')

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (NOT (AND: ('age', 3)))>, ('owner', 'John'))"
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_filter_with_single_Q_object(self):
        """Test query construction with single Q instance as input to `filter` method"""
        # Filter by the Owner
        q1 = Dog.query.filter(Q(owner='John'))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (AND: ('owner', 'John'))>,)"
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_exclude_with_single_Q_object(self):
        """Test query construction with single Q instance as input to `exclude` method"""
        # Filter by the Owner
        q1 = Dog.query.exclude(Q(owner='John'))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (AND: ('owner', 'John'))>,)"
        assert decon_kwargs == {'_negated': True}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is True
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_filter_with_multiple_Q_objects(self):
        """Test query construction with multiple Q objects input to `filter` method"""
        # Filter by the Owner
        q1 = Dog.query.filter(Q(owner='John'), Q(age=3))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (AND: ('owner', 'John'))>, <Q: (AND: ('age', 3))>)"
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_exclude_with_multiple_Q_objects(self):
        """Test query construction with multiple Q objects input to `exclude` method"""
        q1 = Dog.query.exclude(Q(owner='John'), Q(age=3))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (AND: ('owner', 'John'))>, <Q: (AND: ('age', 3))>)"
        assert decon_kwargs == {'_negated': True}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is True
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_filter_with_AND(self):
        """Test query construction with AND"""
        # Filter by the Owner
        q1 = Dog.query.filter(Q(owner='John') & Q(age=3))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (AND: ('owner', 'John'), ('age', 3))>,)"
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_filter_with_OR(self):
        """Test query construction with OR"""
        # Filter by the Owner
        q1 = Dog.query.filter(Q(owner='John') | Q(age=3))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == "(<Q: (OR: ('owner', 'John'), ('age', 3))>,)"
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.OR
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_filter_with_multiple_ANDs(self):
        """Test query construction with multiple AND criteria"""
        # Filter by the Owner
        q1 = Dog.query.filter(Q(owner='John') & Q(age=3) & Q(name='Jean'))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == ("(<Q: (AND: "
                                   "('owner', 'John'), "
                                   "('age', 3), "
                                   "('name', 'Jean'))>,)")
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.AND
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_filter_with_multiple_ORs(self):
        """Test query construction with multiple OR criteria"""
        # Filter by the Owner
        q1 = Dog.query.filter(Q(owner='John') | Q(age=3) | Q(name='Jean'))

        _, decon_args, decon_kwargs = q1._criteria.deconstruct()

        assert str(decon_args) == ("(<Q: (OR: "
                                   "('owner', 'John'), "
                                   "('age', 3), "
                                   "('name', 'Jean'))>,)")
        assert decon_kwargs == {}
        assert q1._criteria.children[0].connector == Q.OR
        assert q1._criteria.negated is False
        assert Q(*decon_args, **decon_kwargs) == q1._criteria

    def test_filter_with_AND_OR_combination(self):
        """Test query construction with AND and OR combinations"""
        # Filter by the Owner
        q1 = Dog.query.filter(Q(owner='John') | Q(age=3), name='Jean')
        _, decon_args, decon_kwargs = q1._criteria.deconstruct()
        assert str(decon_args) == ("(<Q: (OR: ('owner', 'John'), ('age', 3))>, "
                                   "('name', 'Jean'))")
        assert Q(*decon_args, **decon_kwargs) == q1._criteria
        assert q1._criteria.children[0].connector == Q.OR

        q2 = Dog.query.filter((Q(owner='John') | Q(age=3)), Q(name='Jean'))
        _, decon_args, decon_kwargs = q2._criteria.deconstruct()
        assert str(decon_args) == ("(<Q: (OR: ('owner', 'John'), ('age', 3))>, "
                                   "<Q: (AND: ('name', 'Jean'))>)")
        assert Q(*decon_args, **decon_kwargs) == q2._criteria
        assert q2._criteria.children[0].connector == Q.OR

        q3 = Dog.query.filter(Q(name='Jean') & (Q(owner='John') | Q(age=3)))
        _, decon_args, decon_kwargs = q3._criteria.deconstruct()
        assert str(decon_args) == ("(<Q: (AND: "
                                   "('name', 'Jean'), "
                                   "(OR: ('owner', 'John'), ('age', 3)))>,)")
        assert Q(*decon_args, **decon_kwargs) == q3._criteria
        assert q3._criteria.children[0].connector == Q.AND


class TestQ:
    """Class that holds tests for Q Objects"""

    def test_deconstruct(self):
        q = Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert path == 'protean.utils.query.Q'
        assert args == ()
        assert kwargs == {'price__gt': 10.0}

    def test_deconstruct_negated(self):
        q = ~Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert args == ()
        assert kwargs == {
            'price__gt': 10.0,
            '_negated': True,
        }

    def test_deconstruct_or(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q3 = q1 | q2
        path, args, kwargs = q3.deconstruct()
        assert args == (
            ('price__gt', 10.0),
            ('price', 11.0),
        )
        assert kwargs == {'_connector': 'OR'}

    def test_deconstruct_and(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q = q1 & q2
        path, args, kwargs = q.deconstruct()
        assert args == (
            ('price__gt', 10.0),
            ('price', 11.0),
        )
        assert kwargs == {}

    def test_deconstruct_multiple_kwargs(self):
        q = Q(price__gt=10.0, price=11.0)
        path, args, kwargs = q.deconstruct()
        assert args == (
            ('price', 11.0),
            ('price__gt', 10.0),
        )
        assert kwargs == {}

    def test_reconstruct(self):
        q = Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q

    def test_reconstruct_negated(self):
        q = ~Q(price__gt=10.0)
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q

    def test_reconstruct_or(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q = q1 | q2
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q

    def test_reconstruct_and(self):
        q1 = Q(price__gt=10.0)
        q2 = Q(price=11.0)
        q = q1 & q2
        path, args, kwargs = q.deconstruct()
        assert Q(*args, **kwargs) == q


class TestConjunctions:
    """Class that holds tests cases for Conjunctions (AND, OR, NeG)"""

    def test_default_AND(self):
        """Test that kwargs to `filter` are ANDed by default"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        q1 = Dog.query.filter(owner='John', age=3)
        assert q1.total == 1

    def test_default_NEG_AND(self):
        """Test that kwargs to `filter` are ANDed by default"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        q1 = Dog.query.exclude(owner='John', age=3)
        assert q1.total == 1

        q2 = Dog.query.exclude(owner='Carrie', age=10)
        assert q2.total == 2

    def test_simple_AND(self):
        """Test straightforward AND of two criteria"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        q1 = Dog.query.filter(Q(owner='John') & Q(age=3))
        assert q1.total == 1

    def test_simple_OR(self):
        """Test straightforward OR of two criteria"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        q1 = Dog.query.filter(Q(owner='John') | Q(age=3))
        assert q1.total == 2

    def test_AND_with_OR(self):
        """Test combination of AND and OR"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')
        Dog.create(id=5, name='Leslie', age=6, owner='Underwood')
        Dog.create(id=6, name='Dave', age=6, owner='Carrie')

        q1 = Dog.query.filter(
            Q(owner='John', name='Jean') |
            Q(age=6))
        assert q1.total == 4

        q2 = Dog.query.filter(Q(owner='John') | Q(age=6))
        assert q2.total == 5

        q3 = Dog.query.filter(
            (Q(owner='John') & Q(age=7)) |
            (Q(owner='Carrie') & Q(age=6)))
        assert q3.total == 3

    def test_OR_with_AND(self):
        """Test combination of OR and AND"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')
        Dog.create(id=5, name='Leslie', age=6, owner='Underwood')
        Dog.create(id=6, name='Dave', age=6, owner='Carrie')

        q1 = Dog.query.filter((Q(owner='John') | Q(age=7)) & (Q(owner='Carrie') | Q(age=6)))
        assert q1.total == 0

        q2 = Dog.query.filter(
            (Q(owner='John') | Q(age__gte=3)) &
            (Q(name='Jean') | Q(name='Murdock')))
        assert q2.total == 2

    def test_NEG(self):
        """Test Negation of a criteria"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')
        Dog.create(id=5, name='Leslie', age=6, owner='Underwood')
        Dog.create(id=6, name='Dave', age=6, owner='Carrie')

        q1 = Dog.query.filter(~Q(owner='John'))
        assert q1.total == 3

        q2 = Dog.query.filter(~Q(owner='John') | ~Q(age=7))
        assert q2.total == 4

    def test_empty_resultset(self):
        """Test that kwargs to `filter` are ANDed by default"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        q1 = Dog.query.filter(owner='XYZ', age=100)
        assert q1.total == 0
