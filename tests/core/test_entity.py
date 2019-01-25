"""Tests for Entity Functionality and Base Classes"""

import pytest
from tests.support.dog import Dog

from protean.core import field
from protean.core.entity import Entity, QuerySet
from protean.core.exceptions import ObjectNotFoundError
from protean.core.exceptions import ValidationError


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
            del dog.name  # Simulate an error by force-deleting an attribute
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

        dog.update({'age':10})
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

    def test_filter_stored_value(self):
        """ Test that chaining constructs filter sets correctly """
        assert Dog.query.filter(name='Murdock')._filters == {'name': 'Murdock'}
        assert Dog.query.filter(name='Murdock', age=7)._filters == {'name': 'Murdock', 'age': 7}
        assert Dog.query.filter(name='Murdock').filter(age=7)._filters == {'name': 'Murdock', 'age': 7}
        assert Dog.query.filter(name='Murdock').exclude(owner='John')._excludes == {'owner': 'John'}
        assert Dog.query.filter(name='Murdock')._page == 1
        assert Dog.query.filter(name='Murdock').paginate(page=3)._page == 3
        assert Dog.query.filter(name='Murdock')._per_page == 10
        assert Dog.query.filter(name='Murdock').paginate(per_page=25)._per_page == 25
        assert Dog.query.filter(name='Murdock').order_by('name')._order_by == {'name'}

        complex_query = (Dog.query.filter(name='Murdock')
                         .filter(age=7)
                         .exclude(owner='John')
                         .order_by('name')
                         .paginate(page=15, per_page=25))

        assert complex_query._filters == {'name': 'Murdock', 'age': 7}
        assert complex_query._excludes == {'owner': 'John'}
        assert complex_query._page == 15
        assert complex_query._per_page == 25
        assert complex_query._order_by == {'name'}

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
        """Query the resository with exclusion filters"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = Dog.query.exclude(name=['Murdock', 'Jean'])
        assert dogs is not None
        assert dogs.total == 1
        assert len(dogs.items) == 1
        assert dogs.first.age == 6
        assert dogs.first.name == 'Bart'

    def test_pagination(self):
        """ Test the pagination of the filter results"""
        for counter in range(1, 5):
            Dog.create(id=counter, name=counter, owner='Owner Name')

        dogs = Dog.query.paginate(per_page=2).order_by('id')
        assert dogs is not None
        assert dogs.total == 4
        assert len(dogs.items) == 2
        assert dogs.first.id == 1
        assert dogs.has_next
        assert not dogs.has_prev

        dogs = Dog.query.paginate(page=2, per_page=2).order_by('id')
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
        assert repr(query) == ("<QuerySet: {'_entity_cls_name': 'Dog', '_page': 1, "
                               "'_per_page': 10, '_order_by': {'age'}, '_excludes': {}, "
                               "'_filters': {'owner': 'John'}}>")

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

    def test_total(self):
        """Test value of `total` results"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')
        assert query.total == 2

    def test_items(self):
        """Test that items is retrieved from Pagination results"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.filter(owner='John').order_by('age')
        assert query.items[0].id == query.all().items[0].id

    def test_has_next(self):
        """Test if there are results after the current set"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.paginate(page=1, per_page=2)
        assert query.has_next is True

    def test_has_prev(self):
        """Test if there are results before the current set"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.paginate(page=2, per_page=2)
        assert query.has_prev is True

    def test_first(self):
        """Test that the first item is retrieved correctly from the resultset"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = Dog.query.order_by('-age')
        assert query.first.id == 2
