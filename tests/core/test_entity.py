"""Tests for Entity Functionality and Base Classes"""

import pytest
from tests.support.dog import Dog, RelatedDog
from tests.support.human import Human

from protean.core import field
from protean.core.entity import Entity, QuerySet
from protean.core.exceptions import ObjectNotFoundError
from protean.core.exceptions import ValidationError, ValueError
from protean.utils.query import Q


class TestEntity:
    """This class holds tests for Base Entity Abstract class"""

    def test_init(self):
        """Test successful Account Entity initialization"""

        dog = Dog(
            id=1, name='John Doe', age=10, owner='Jimmy')
        assert dog is not None
        assert dog.name == 'John Doe'
        assert dog.age == 10
        assert dog.owner == 'Jimmy'

    def test_individuality(self):
        """Test successful Account Entity initialization"""

        dog1 = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        dog2 = Dog(id=2, name='Jimmy Kane', age=3, owner='John')
        assert dog1.name == 'John Doe'
        assert dog1.age == 10
        assert dog1.owner == 'Jimmy'
        assert dog2.name == 'Jimmy Kane'
        assert dog2.age == 3
        assert dog2.owner == 'John'

    def test_required_fields(self):
        """Test errors if mandatory fields are missing"""

        with pytest.raises(ValidationError):
            Dog(id=2, name='John Doe')

    def test_defaults(self):
        """Test that values are defaulted properly"""
        dog = Dog(
            id=1, name='John Doe', owner='Jimmy')
        assert dog.age == 5

    def test_validate_string_length(self):
        """Test validation of String length checks"""
        with pytest.raises(ValidationError):
            Dog(id=1, name='John Doe',
                owner='12345678901234567890')

    def test_validate_data_value_against_type(self):
        """Test validation of data types of values"""
        with pytest.raises(ValidationError):
            Dog(id=1, name='John Doe',
                owner='1234567890',
                age="foo")

    def test_template_init(self):
        """Test initialization using a template dictionary"""
        with pytest.raises(AssertionError):
            Dog('Dummy')

        dog = Dog(
            dict(id=1, name='John Doe', owner='Jimmy'))
        assert dog.name == 'John Doe'
        assert dog.owner == 'Jimmy'

    def test_error_messages(self):
        """Test the correct error messages are generated"""

        # Test single error message
        try:
            Dog(id=1, name='John Doe', owner='Jimmy')
        except ValidationError as err:
            assert err.normalized_messages == {
                'owner': [Dog.owner.error_messages['required']]}

        # Test multiple error messages
        try:
            Dog(id=1, name='Joh', owner='Jimmy')
        except ValidationError as err:
            assert err.normalized_messages == {
                'name': ['Ensure value has at least 5 characters.'],
                'owner': [Dog.owner.error_messages['required']]}

    def test_entity_inheritance(self):
        """ Test that subclasses of `Entity` can be inherited"""

        class SharedEntity(Entity):
            """ Class that provides the default fields """
            age = field.Integer(default=5)

        class Dog2(SharedEntity):
            """This is a dummy Dog Entity class with a mixin"""
            id = field.Integer(identifier=True)
            name = field.String(required=True, max_length=50, min_length=5)
            owner = field.String(required=True, max_length=15)

        dog2 = Dog2(
            id=3, name='John Doe', owner='Jimmy')
        assert dog2 is not None
        assert dog2.age == 5

    def test_default_id(self):
        """ Test that default id field is assigned when not defined"""

        class Dog2(Entity):
            """This is a dummy Dog Entity class without an id"""
            name = field.String(required=True, max_length=50, min_length=5)

        dog2 = Dog2(
            id=3, name='John Doe')
        assert dog2 is not None
        assert dog2.id == 3

    def test_to_dict(self):
        """Test conversion of the entity to dict"""

        dog = Dog(
            id=1, name='John Doe', age=10, owner='Jimmy')
        assert dog is not None
        assert dog.to_dict() == {
            'age': 10, 'id': 1, 'name': 'John Doe', 'owner': 'Jimmy'}

    def test_get(self):
        """Test Entity Retrieval by its primary key"""
        Dog.create(id=1234, name='Johnny', owner='John')

        dog = Dog.get(1234)
        assert dog is not None
        assert dog.id == 1234

    def test_get_object_not_found_error(self):
        """Test failed Entity Retrieval by its primary key"""
        Dog.create(id=1234, name='Johnny', owner='John')

        with pytest.raises(ObjectNotFoundError):
            Dog.get(1235)

    def test_find_by(self):
        """Test Entity retrieval by a specific column's value"""

        Dog.create(id=2345, name='Johnny', owner='John')

        dog = Dog.find_by(name='Johnny')
        assert dog is not None
        assert dog.id == 2345

    def test_find_by_object_not_found_error(self):
        """Test Entity retrieval by specific column value(s)"""

        Dog.create(id=2345, name='Johnny', owner='John')

        with pytest.raises(ObjectNotFoundError):
            Dog.find_by(name='JohnnyChase')

    def test_find_by_multiple_attributes(self):
        """Test Entity retrieval by multiple column value(s)"""

        Dog.create(id=2346, name='Johnny1', age=8, owner='John')
        Dog.create(id=2347, name='Johnny2', age=6, owner='John')

        dog = Dog.find_by(name='Johnny1', age=8)
        assert dog is not None
        assert dog.id == 2346

    def test_find_by_multiple_attributes_object_not_found_error(self):
        """Test Entity retrieval by multiple column value(s)"""

        Dog.create(id=2346, name='Johnny1', age=8, owner='John')
        Dog.create(id=2347, name='Johnny2', age=6, owner='John')

        with pytest.raises(ObjectNotFoundError):
            Dog.find_by(name='Johnny1', age=6)

    def test_create_error(self):
        """ Add an entity to the repository missing a required attribute"""
        with pytest.raises(ValidationError):
            Dog.create(owner='John')

    def test_create(self):
        """ Add an entity to the repository"""
        dog = Dog.create(id=11344234, name='Johnny', owner='John')
        assert dog is not None
        assert dog.id == 11344234
        assert dog.name == 'Johnny'
        assert dog.age == 5
        assert dog.owner == 'John'

        dog = Dog.get(11344234)
        assert dog is not None

    def test_save(self):
        """Initialize an entity and save it to repository"""
        dog = Dog(name='Johnny', owner='John')

        saved_dog = dog.save()
        assert saved_dog is not None
        assert saved_dog.id is not None
        assert saved_dog.name == 'Johnny'
        assert saved_dog.age == 5
        assert saved_dog.owner == 'John'

    def test_save_validation_error(self):
        """Test failed `save()` because of validation errors"""
        dog = Dog(name='Johnny', owner='John')

        with pytest.raises(ValidationError):
            dog.name = ""  # Simulate an error by force-resetting an attribute
            dog.save()

    def test_save_invalid_value(self):
        """Initialize an entity and save it to repository"""
        dog = Dog(name='Johnny', owner='John')

        with pytest.raises(ValidationError):
            dog.age = 'abcd'
            dog.save()

    def test_update_with_invalid_id(self):
        """Try to update a non-existing entry"""

        dog = Dog.create(id=11344234, name='Johnny', owner='John')
        dog.delete()
        with pytest.raises(ObjectNotFoundError):
            dog.update({'age': 10})

    def test_update_with_dict(self):
        """ Update an existing entity in the repository"""
        dog = Dog.create(id=2, name='Johnny', owner='Carey', age=2)

        dog.update({'age': 10})
        u_dog = Dog.get(2)
        assert u_dog is not None
        assert u_dog.age == 10

    def test_update_with_kwargs(self):
        """ Update an existing entity in the repository"""
        dog = Dog.create(id=2, name='Johnny', owner='Carey', age=2)

        dog.update(age=10)
        u_dog = Dog.get(2)
        assert u_dog is not None
        assert u_dog.age == 10

    def test_update_with_dict_and_kwargs(self):
        """ Update an existing entity in the repository"""
        dog = Dog.create(id=2, name='Johnny', owner='Carey', age=2)

        dog.update({'owner': 'Stephen'}, age=10)
        u_dog = Dog.get(2)
        assert u_dog is not None
        assert u_dog.age == 10
        assert u_dog.owner == 'Stephen'

    def test_that_update_runs_validations(self):
        """Try updating with invalid values"""
        dog = Dog.create(id=1, name='Johnny', owner='Carey', age=2)

        with pytest.raises(ValidationError):
            dog.update(age='x')

    def test_unique(self):
        """ Test the unique constraints for the entity """
        Dog.create(id=2, name='Johnny', owner='Carey')

        with pytest.raises(ValidationError) as err:
            Dog.create(
                id=2, name='Johnny', owner='Carey')
        assert err.value.normalized_messages == {
            'name': ['`dogs` with this `name` already exists.']}

    def test_query_init(self):
        """Test the initialization of a QuerySet"""
        query = Dog.query

        assert query is not None
        assert isinstance(query, QuerySet)
        assert vars(query) == vars(QuerySet('Dog'))

    def test_filter_chain_initialization_from_entity(self):
        """ Test that chaining returns a QuerySet for further chaining """
        filters = [
            Dog.query.filter(name='Murdock'),
            Dog.query.filter(name='Jean').filter(owner='John'),
            Dog.query.paginate(page=5),
            Dog.query.paginate(per_page=25),
            Dog.query.order_by('name'),
            Dog.query.exclude(name='Murdock')
        ]

        for filter in filters:
            assert isinstance(filter, QuerySet)

    def test_filter_chaining(self):
        """ Test that chaining returns a QuerySet for further chaining """
        dog = Dog.query.filter(name='Murdock')
        filters = [
            dog,
            Dog.query.filter(name='Jean').filter(owner='John'),
            dog.paginate(page=5),
            dog.paginate(per_page=5),
            dog.order_by('name'),
            dog.exclude(name='Murdock')
        ]

        for filter in filters:
            assert isinstance(filter, QuerySet)

    def test_filter_chain_results_1(self):
        """ Chain filter method invocations to construct a complex filter """
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(name='Jean').filter(owner='John').filter(age=3)
        dogs = query.all()

        assert dogs is not None
        assert dogs.total == 1
        assert len(dogs.items) == 1

        dog = dogs.first
        assert dog.id == 3

    def test_filter_chain_results_2(self):
        """ Chain filter method invocations to construct a complex filter """
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John')
        dogs = query.all()

        assert dogs is not None
        assert dogs.total == 2
        assert len(dogs.items) == 2

        dog = dogs.first
        assert dog.id == 2

    def test_filter_chain_results_3(self):
        """ Chain filter method invocations to construct a complex filter """
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')
        dogs = query.all()

        assert dogs is not None
        assert dogs.total == 2
        assert len(dogs.items) == 2

        dog = dogs.first
        assert dog.id == 3

    def test_filter_norm(self):
        """ Query the repository using filters """
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = Dog.query.filter(owner='John')
        assert dogs is not None
        assert dogs.total == 2
        assert len(dogs.items) == 2

        # Order the results by age
        dogs = Dog.query.filter(owner='John').order_by('-age')
        assert dogs is not None
        assert dogs.first.age == 7
        assert dogs.first.name == 'Murdock'

    def test_exclude(self):
        """Query the resository with exclusion filters"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = Dog.query.exclude(owner='John')
        assert dogs is not None
        assert dogs.total == 1
        assert len(dogs.items) == 1
        assert dogs.first.age == 6
        assert dogs.first.name == 'Bart'

    def test_exclude_multiple(self):
        """Query the repository with exclusion filters"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = Dog.query.exclude(name__in=['Murdock', 'Jean'])
        assert dogs is not None
        assert dogs.total == 1
        assert len(dogs.items) == 1
        assert dogs.first.age == 6
        assert dogs.first.name == 'Bart'

    def test_comparisons(self):
        """Query with greater than operator"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='john')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs_gte = Dog.query.filter(age__gte=3)
        dogs_lte = Dog.query.filter(age__lte=6)
        dogs_gt = Dog.query.filter(age__gt=3)
        dogs_lt = Dog.query.filter(age__lt=6)
        dogs_in = Dog.query.filter(name__in=['Jean', 'Bart', 'Nobody'])
        dogs_exact = Dog.query.filter(owner__exact='John')
        dogs_iexact = Dog.query.filter(owner__iexact='John')
        dogs_contains = Dog.query.filter(owner__contains='Joh')
        dogs_icontains = Dog.query.filter(owner__icontains='Joh')

        assert dogs_gte.total == 3
        assert dogs_lte.total == 2
        assert dogs_gt.total == 2
        assert dogs_lt.total == 1
        assert dogs_in.total == 2
        assert dogs_exact.total == 1
        assert dogs_iexact.total == 2
        assert dogs_contains.total == 1
        assert dogs_icontains.total == 2

    def test_invalid_comparison_on_query_evaluation(self):
        """Query with an invalid/unimplemented comparison"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='john')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        with pytest.raises(NotImplementedError):
            Dog.query.filter(age__notexact=3).all()

    def test_pagination(self):
        """ Test the pagination of the filter results"""
        for counter in range(1, 5):
            Dog.create(id=counter, name=counter, owner='Owner Name')

        dogs = Dog.query.paginate(per_page=2).order_by('id')
        assert dogs.total == 4
        assert len(dogs.items) == 2
        assert dogs.first.id == 1
        assert dogs.has_next
        assert not dogs.has_prev

        dogs = Dog.query.paginate(page=2, per_page=2).order_by('id').all()
        assert len(dogs.items) == 2
        assert dogs.first.id == 3
        assert not dogs.has_next
        assert dogs.has_prev

    def test_delete(self):
        """ Delete an object in the reposoitory by ID"""
        dog = Dog.create(id=3, name='Johnny', owner='Carey')
        del_count = dog.delete()
        assert del_count == 1

        del_count = dog.delete()
        assert del_count == 0

        with pytest.raises(ObjectNotFoundError):
            Dog.get(3)

    def test_filter_returns_q_object(self):
        """Test Negation of a criteria"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        query = Dog.query.filter(owner='John')
        assert isinstance(query, QuerySet)

    class TestState:
        """Class that holds tests for Entity State Management"""

        def test_default_state(self):
            """Test that a default state is available when the entity is instantiated"""
            dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
            assert dog._state is not None
            assert dog._state._new
            assert dog._state.is_new()
            assert dog.is_new
            assert not dog.is_persisted

        def test_state_on_retrieved_objects(self):
            """Test that retrieved objects are not marked as new"""
            dog = Dog.create(name='John Doe', age=10, owner='Jimmy')
            dog_dup = Dog.get(dog.id)

            assert not dog_dup.is_new

        def test_persisted_after_save(self):
            """Test that the entity is marked as saved after successfull save"""
            dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
            assert dog.is_new
            dog.save()
            assert dog.is_persisted

        def test_not_persisted_if_save_failed(self):
            """Test that the entity still shows as new if save failed"""
            dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
            try:
                del dog.name
                dog.save()
            except ValidationError as exc:
                assert dog.is_new

        def test_persisted_after_create(self):
            """Test that the entity is marked as saved after successfull create"""
            dog = Dog.create(id=1, name='John Doe', age=10, owner='Jimmy')
            assert not dog.is_new

        def test_copy_resets_state(self):
            """Test that a default state is available when the entity is instantiated"""
            dog1 = Dog.create(id=1, name='John Doe', age=10, owner='Jimmy')
            dog2 = dog1.clone()

            assert dog2.is_new

        def test_changed(self):
            """Test that entity is marked as changed if attributes are updated"""
            dog = Dog.create(id=1, name='John Doe', age=10, owner='Jimmy')
            assert not dog.is_changed
            dog.name = 'Jane Doe'
            assert dog.is_changed

        def test_not_changed_if_still_new(self):
            """Test that entity is not marked as changed upon attribute change if its still new"""
            dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
            assert not dog.is_changed
            dog.name = 'Jane Doe'
            assert not dog.is_changed

        def test_not_changed_after_save(self):
            """Test that entity is marked as not changed after save"""
            dog = Dog.create(id=1, name='John Doe', age=10, owner='Jimmy')
            dog.name = 'Jane Doe'
            assert dog.is_changed
            dog.save()
            assert not dog.is_changed

        def test_destroyed(self):
            """Test that a entity is marked as destroyed after delete"""
            dog = Dog.create(id=1, name='John Doe', age=10, owner='Jimmy')
            assert not dog.is_destroyed
            dog.delete()
            assert dog.is_destroyed


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
        assert repr(query) == ("<QuerySet: entity: Dog, "
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


class TestAssociations:
    """Class that holds tests cases for Entity Associations"""

    class TestReference:
        """Class to test References (Foreign Key) Association"""

        def test_init(self):
            """Test successful RelatedDog initialization"""
            human = Human.create(first_name='Jeff', last_name='Kennedy',
                                 email='jeff.kennedy@presidents.com')
            dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
            assert dog.owner == human

        def test_save(self):
            """Test successful RelatedDog save"""
            human = Human.create(first_name='Jeff', last_name='Kennedy',
                                 email='jeff.kennedy@presidents.com')
            dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
            dog.save()
            assert dog.id is not None

        def test_unsaved_entity_init(self):
            """Test that initialization fails when an unsaved entity is assigned to a relation"""
            with pytest.raises(ValueError):
                human = Human(first_name='Jeff', last_name='Kennedy', email='jeff.kennedy@presidents.com')
                RelatedDog(id=1, name='John Doe', age=10, owner=human)

        def test_unsaved_entity_assign(self):
            """Test that assignment fails when an unsaved entity is assigned to a relation"""
            with pytest.raises(ValueError):
                human = Human(first_name='Jeff', last_name='Kennedy',
                              email='jeff.kennedy@presidents.com')
                dog = RelatedDog(id=1, name='John Doe', age=10)
                dog.owner = human

        def test_invalid_entity_type(self):
            """Test that assignment fails when an invalid entity type is assigned to a relation"""
            with pytest.raises(ValidationError):
                dog = Dog.create(name='Johnny', owner='John')
                related_dog = RelatedDog(id=1, name='John Doe', age=10)
                related_dog.owner = dog

        def test_shadow_attribute(self):
            """Test identifier backing the association"""
            human = Human.create(first_name='Jeff', last_name='Kennedy',
                                 email='jeff.kennedy@presidents.com')
            dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
            assert human.id is not None
            assert dog.owner_id == human.id

        def test_save_after_assign(self):
            """Test identifier backing the association"""
            human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                                 email='jeff.kennedy@presidents.com')
            dog = RelatedDog(id=1, name='John Doe', age=10)
            dog.owner = human
            assert dog.owner_id == human.id

        def test_shadow_attribute_init(self):
            """Test identifier backing the association"""
            human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                                 email='jeff.kennedy@presidents.com')
            dog = RelatedDog(id=1, name='John Doe', age=10, owner_id=human.id)
            dog.save()
            assert dog.owner_id == human.id
            assert dog.owner.id == human.id

        def test_shadow_attribute_assign(self):
            """Test identifier backing the association"""
            human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                                 email='jeff.kennedy@presidents.com')
            dog = RelatedDog(id=1, name='John Doe', age=10)
            dog.owner_id = human.id
            dog.save()
            assert dog.owner_id == human.id
            assert dog.owner.id == human.id

        def test_reference_reset_association_to_None(self):
            """Test that the reference field and shadow attribute are reset together"""
            human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                                 email='jeff.kennedy@presidents.com')
            dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
            assert dog.owner_id == human.id
            assert dog.owner.id == human.id

            dog.owner = None
            assert dog.owner is None
            assert dog.owner_id is None

        def test_reference_reset_shadow_field_to_None(self):
            """Test that the reference field and shadow attribute are reset together"""
            human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                                 email='jeff.kennedy@presidents.com')
            dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
            assert dog.owner_id == human.id
            assert dog.owner.id == human.id

            dog.owner_id = None
            assert dog.owner is None
            assert dog.owner_id is None

        def test_reference_reset_association_by_del(self):
            """Test that the reference field and shadow attribute are reset together"""
            human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                                 email='jeff.kennedy@presidents.com')
            dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
            assert dog.owner_id == human.id
            assert dog.owner.id == human.id

            del dog.owner
            assert dog.owner is None
            assert dog.owner_id is None

        def test_reference_reset_shadow_field_by_del(self):
            """Test that the reference field and shadow attribute are reset together"""
            human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                                 email='jeff.kennedy@presidents.com')
            dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
            assert dog.owner_id == human.id
            assert dog.owner.id == human.id

            del dog.owner_id
            assert dog.owner is None
            assert dog.owner_id is None
