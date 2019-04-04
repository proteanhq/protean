"""Tests for Entity Functionality and Base Classes"""

from collections import OrderedDict

import pytest
from tests.support.dog import Dog
from tests.support.dog import HasOneDog1
from tests.support.dog import RelatedDog
from tests.support.human import HasOneHuman1
from tests.support.human import Human

from protean.core import field
from protean.core.entity import Entity
from protean.core.entity import QuerySet
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

    def test_update_by(self):
        """Test that update by query updates only correct records"""
        Dog.create(id=1, name='Athos', owner='John', age=2)
        Dog.create(id=2, name='Porthos', owner='John', age=3)
        Dog.create(id=3, name='Aramis', owner='John', age=4)
        Dog.create(id=4, name='dArtagnan', owner='John', age=5)

        # Perform update
        updated_count = Dog.query.filter(age__gt=3).update(owner='Jane')

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_dog1 = Dog.get(1)
        u_dog2 = Dog.get(2)
        u_dog3 = Dog.get(3)
        u_dog4 = Dog.get(4)
        assert u_dog1.owner == 'John'
        assert u_dog2.owner == 'John'
        assert u_dog3.owner == 'Jane'
        assert u_dog4.owner == 'Jane'

    def test_update_all_with_args(self):
        """Try updating all records satisfying filter in one step, passing a dict"""
        Dog.create(id=1, name='Athos', owner='John', age=2)
        Dog.create(id=2, name='Porthos', owner='John', age=3)
        Dog.create(id=3, name='Aramis', owner='John', age=4)
        Dog.create(id=4, name='dArtagnan', owner='John', age=5)

        # Perform update
        updated_count = Dog.query.filter(age__gt=3).update_all({'owner': 'Jane'})

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_dog1 = Dog.get(1)
        u_dog2 = Dog.get(2)
        u_dog3 = Dog.get(3)
        u_dog4 = Dog.get(4)
        assert u_dog1.owner == 'John'
        assert u_dog2.owner == 'John'
        assert u_dog3.owner == 'Jane'
        assert u_dog4.owner == 'Jane'

    def test_update_all_with_kwargs(self):
        """Try updating all records satisfying filter in one step"""
        Dog.create(id=1, name='Athos', owner='John', age=2)
        Dog.create(id=2, name='Porthos', owner='John', age=3)
        Dog.create(id=3, name='Aramis', owner='John', age=4)
        Dog.create(id=4, name='dArtagnan', owner='John', age=5)

        # Perform update
        updated_count = Dog.query.filter(age__gt=3).update_all(owner='Jane')

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_dog1 = Dog.get(1)
        u_dog2 = Dog.get(2)
        u_dog3 = Dog.get(3)
        u_dog4 = Dog.get(4)
        assert u_dog1.owner == 'John'
        assert u_dog2.owner == 'John'
        assert u_dog3.owner == 'Jane'
        assert u_dog4.owner == 'Jane'

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
        assert vars(query) == vars(QuerySet(Dog))

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
        deleted_dog = dog.delete()
        assert deleted_dog is not None
        assert deleted_dog.state_.is_destroyed is True

        with pytest.raises(ObjectNotFoundError):
            Dog.get(3)

    def test_delete_all(self):
        """Try updating all records satisfying filter in one step, passing a dict"""
        Dog.create(id=1, name='Athos', owner='John', age=2)
        Dog.create(id=2, name='Porthos', owner='John', age=3)
        Dog.create(id=3, name='Aramis', owner='John', age=4)
        Dog.create(id=4, name='dArtagnan', owner='John', age=5)

        # Perform update
        deleted_count = Dog.query.filter(age__gt=3).delete_all()

        # Query and check if only the relevant records have been deleted
        assert deleted_count == 2

        dog1 = Dog.get(1)
        dog2 = Dog.get(2)

        assert dog1 is not None
        assert dog2 is not None

        with pytest.raises(ObjectNotFoundError):
            Dog.get(3)

        with pytest.raises(ObjectNotFoundError):
            Dog.get(4)

    def test_delete_by(self):
        """Test that update by query updates only correct records"""
        Dog.create(id=1, name='Athos', owner='John', age=2)
        Dog.create(id=2, name='Porthos', owner='John', age=3)
        Dog.create(id=3, name='Aramis', owner='John', age=4)
        Dog.create(id=4, name='dArtagnan', owner='John', age=5)

        # Perform update
        deleted_count = Dog.query.filter(age__gt=3).delete()

        # Query and check if only the relevant records have been updated
        assert deleted_count == 2
        assert Dog.query.all().total == 2

        assert Dog.get(1) is not None
        assert Dog.get(2) is not None
        with pytest.raises(ObjectNotFoundError):
            Dog.get(3)

        with pytest.raises(ObjectNotFoundError):
            Dog.get(4)

    def test_filter_returns_q_object(self):
        """Test Negation of a criteria"""
        # Add multiple entries to the DB
        Dog.create(id=2, name='Murdock', age=7, owner='John')
        Dog.create(id=3, name='Jean', age=3, owner='John')
        Dog.create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        query = Dog.query.filter(owner='John')
        assert isinstance(query, QuerySet)


class TestEntityMetaAttributes:

    """Class that holds testcases for Entity's meta attributes"""

    def test_meta_on_init(self):
        """Test that `meta` attribute is available after initialization"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        assert hasattr(dog, 'meta_')

    def test_declared_fields_normal(self):
        """Test declared fields on an entity without references"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')

        attribute_keys = list(OrderedDict(sorted(dog.meta_.attributes.items())).keys())
        assert attribute_keys == ['age', 'id', 'name', 'owner']

    def test_declared_fields_with_reference(self):
        """Test declared fields on an entity with references"""
        human = Human.create(first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)

        attribute_keys = list(OrderedDict(sorted(dog.meta_.attributes.items())).keys())
        assert attribute_keys == ['age', 'id', 'name', 'owner_id']

    def test_declared_fields_with_hasone_association(self):
        """Test declared fields on an entity with a HasOne association"""
        human = HasOneHuman1.create(first_name='Jeff', last_name='Kennedy',
                                    email='jeff.kennedy@presidents.com')
        dog = HasOneDog1.create(id=1, name='John Doe', age=10, has_one_human1=human)

        assert all(key in dog.meta_.attributes for key in ['age', 'has_one_human1_id', 'id', 'name'])
        assert all(key in human.meta_.attributes for key in ['first_name', 'id', 'last_name', 'email'])
