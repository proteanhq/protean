"""Tests for Entity Functionality and Base Classes"""

from collections import OrderedDict
from datetime import datetime

import pytest
from tests.support.dog import Dog
from tests.support.dog import HasOneDog1
from tests.support.dog import RelatedDog
from tests.support.dog import SubDog
from tests.support.human import HasOneHuman1
from tests.support.human import Human

from protean import Entity
from protean.core import field
from protean.core.exceptions import InvalidOperationError
from protean.core.exceptions import NotSupportedError
from protean.core.exceptions import ObjectNotFoundError
from protean.core.exceptions import ValidationError
from protean.core.queryset import QuerySet


class TestEntity:
    """This class holds tests for Base Entity Abstract class"""

    def test_init(self):
        """Test successful Account Entity initialization"""

        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        assert dog is not None
        assert dog.name == 'John Doe'
        assert dog.age == 10
        assert dog.owner == 'Jimmy'

    def test_individuality(self):
        """Test successful Account Entity initialization"""

        dog1 = Dog(name='John Doe', age=10, owner='Jimmy')
        dog2 = Dog(name='Jimmy Kane', age=3, owner='John')
        assert dog1.name == 'John Doe'
        assert dog1.age == 10
        assert dog1.owner == 'Jimmy'
        assert dog2.name == 'Jimmy Kane'
        assert dog2.age == 3
        assert dog2.owner == 'John'

    def test_equality_of_entities_1(self):
        """Test that two entities are considered equal based on their ID"""
        dog1 = Dog.create(name='Slobber 1', age=6, owner='Jason')
        dog2 = Dog.create(name='Slobber 2', age=6, owner='Jason')

        assert dog1 != dog2  # Because their identities are different
        assert dog2 != dog1  # Because their identities are different

        db_dog = Dog.get(1)
        assert dog1 == db_dog  # Because it's the same record but reloaded from db
        assert db_dog == dog1  # Because it's the same record but reloaded from db

    def test_equality_of_entities_2(self):
        """Test that two entities are not considered equal even if they have the same ID
            and one belongs to a different Entity class
        """
        dog = Dog.create(id=1, name='Slobber 1', age=6, owner='Jason')
        human = Human.create(id=1, first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')

        assert dog != human  # Even though their identities are the same
        assert human != dog  # Even though their identities are the same

    def test_equality_of_entities_3(self):
        """Test that two entities are not considered equal even if they have the same ID
            and one is subclassed from the other
        """
        dog = Dog.create(id=1, name='Slobber 1', age=6, owner='Jason')
        subdog = SubDog.create(id=1, name='Slobber 1', age=6, owner='Jason')

        assert dog != subdog  # Even though their identities are the same
        assert subdog != dog  # Even though their identities are the same

    def test_entity_hash(self):
        """Test that the entity's hash is based on its identity"""
        hashed_id = hash(1)

        dog = Dog.create(id=1, name='Slobber 1', age=6, owner='Jason')
        assert hashed_id == hash(dog)

    def test_required_fields(self):
        """Test errors if required fields are missing"""

        with pytest.raises(ValidationError):
            Dog(name='John Doe')

    def test_defaults(self):
        """Test that values are defaulted properly"""
        dog = Dog(name='John Doe', owner='Jimmy')
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

        dog = Dog(dict(name='John Doe', owner='Jimmy'))
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
        @Entity
        class SharedEntity:
            """ Class that provides the default fields """
            age = field.Integer(default=5)

        @Entity
        class Dog2(SharedEntity):
            """This is a dummy Dog Entity class with a mixin"""
            name = field.String(required=True, max_length=50, min_length=5)
            owner = field.String(required=True, max_length=15)

        dog2 = Dog2(id=3, name='John Doe', owner='Jimmy')
        assert dog2 is not None
        assert dog2.age == 5

    def test_inhertied_entity_schema(self):
        """ Test that subclasses of `Entity` can be inherited"""

        class Dog2(Dog):
            """This is a dummy Dog Entity class with a mixin"""
            pass

        assert Dog.meta_.schema_name != Dog2.meta_.schema_name

    def test_default_id(self):
        """ Test that default id field is assigned when not defined"""

        @Entity
        class Dog2:
            """This is a dummy Dog Entity class without an id"""
            name = field.String(required=True, max_length=50, min_length=5)

        dog2 = Dog2(id=3, name='John Doe')
        assert dog2 is not None
        assert dog2.id == 3

    def test_id_immutability(self):
        """Test that `id` cannot be changed once assigned"""
        dog = Dog(id=4, name='Chucky', owner='John Doe')
        dog.save()

        assert dog.state_.is_persisted is True

        with pytest.raises(InvalidOperationError):
            dog.update(id=5)

    def test_to_dict(self):
        """Test conversion of the entity to dict"""

        dog = Dog(
            id=1, name='John Doe', age=10, owner='Jimmy')
        assert dog is not None
        assert dog.to_dict() == {
            'age': 10, 'id': 1, 'name': 'John Doe', 'owner': 'Jimmy'}

    def test_repr(self):
        """Test that a meaningful repr is printed for entities"""
        dog1 = Dog(name='John Doe', age=10, owner='Jimmy')
        assert str(dog1) == 'Dog object (id: None)'
        assert repr(dog1) == '<Dog: Dog object (id: None)>'

        dog2 = Dog.create(id=1, name='Jimmy', age=10, owner='John Doe')
        assert str(dog2) == 'Dog object (id: 1)'
        assert repr(dog2) == '<Dog: Dog object (id: 1)>'

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

    def test_save_again(self):
        """Test that save can be invoked again on an already existing entity, to update values"""
        dog = Dog(name='Johnny', owner='John')
        dog.save()

        dog.name = 'Janey'
        dog.save()

        dog.reload()
        assert dog.name == 'Janey'

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
        Dog.create(id=4, name='d\'Artagnan', owner='John', age=5)

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
        Dog.create(id=4, name='d\'Artagnan', owner='John', age=5)

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
        Dog.create(id=4, name='d\'Artagnan', owner='John', age=5)

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
            'name': ['`Dog` with this `name` already exists.']}

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
            Dog.query.offset(1),
            Dog.query.limit(25),
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
            dog.offset(5 * 5),
            dog.limit(5),
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

    def test_result_traversal(self):
        """ Test the traversal of the filter results"""
        for counter in range(1, 5):
            Dog.create(id=counter, name=counter, owner='Owner Name')

        dogs = Dog.query.limit(2).order_by('id')
        assert dogs.total == 4
        assert len(dogs.items) == 2
        assert dogs.first.id == 1
        assert dogs.has_next
        assert not dogs.has_prev

        dogs = Dog.query.offset(2).limit(2).order_by('id').all()
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
        """Clean up repository and delete all records"""
        Dog.create(id=1, name='Athos', owner='John', age=2)
        Dog.create(id=2, name='Porthos', owner='John', age=3)
        Dog.create(id=3, name='Aramis', owner='John', age=4)
        Dog.create(id=4, name='d\'Artagnan', owner='John', age=5)

        dogs = Dog.query.all()
        assert dogs.total == 4

        Dog.delete_all()

        dogs = Dog.query.all()
        assert dogs.total == 0

    def test_delete_all_by_filter(self):
        """Try updating all records satisfying filter in one step, passing a dict"""
        Dog.create(id=1, name='Athos', owner='John', age=2)
        Dog.create(id=2, name='Porthos', owner='John', age=3)
        Dog.create(id=3, name='Aramis', owner='John', age=4)
        Dog.create(id=4, name='d\'Artagnan', owner='John', age=5)

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
        Dog.create(id=4, name='d\'Artagnan', owner='John', age=5)

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

    def test_escaped_quotes_in_values(self):
        """Test that escaped quotes in values are handled properly"""

        Dog.create(name='Athos', owner='John', age=2)
        Dog.create(name='Porthos', owner='John', age=3)
        Dog.create(name='Aramis', owner='John', age=4)

        dog1 = Dog.create(name="d'Artagnan1", owner='John', age=5)
        dog2 = Dog.create(name="d\'Artagnan2", owner='John', age=5)
        dog3 = Dog.create(name="d\"Artagnan3", owner='John', age=5)
        dog4 = Dog.create(name='d\"Artagnan4', owner='John', age=5)

        assert all(dog is not None for dog in [dog1, dog2, dog3, dog4])

    def test_override(self, test_domain):
        """Test overriding methods from Entity"""

        @Entity
        class ImmortalDog:
            """A Dog who lives forever"""

            name = field.String(required=True, unique=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

            def delete(self):
                """You can't delete me!!"""
                raise SystemError("Deletion Prohibited!")

        test_domain.register_element(ImmortalDog)

        immortal_dog = ImmortalDog.create(name='Titan', age=10001, owner='God')
        with pytest.raises(SystemError):
            immortal_dog.delete()

        test_domain.unregister_element(ImmortalDog)

    def test_abstract(self):
        """Test that abstract entities cannot be initialized"""
        @Entity
        class AbstractDog:
            """A Dog that cannot Live!"""
            name = field.String(required=True, unique=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)

            class Meta:
                abstract = True

        with pytest.raises(NotSupportedError) as exc1:
            from protean.core.repository import repo_factory
            repo_factory.register(AbstractDog)
        assert exc1.value.args[0] == ('AbstractDog class has been marked abstract'
                                      ' and cannot be instantiated')

        with pytest.raises(NotSupportedError) as exc2:
            AbstractDog(name='Titan', age=10001, owner='God')
        assert exc2.value.args[0] == ('AbstractDog class has been marked abstract'
                                      ' and cannot be instantiated')

    def test_abstract_inheritance(self):
        """Test that abstract entities cannot be initialized"""
        @Entity
        class AbstractDog:
            """A Dog that cannot Live!"""
            age = field.Integer(default=5)

            class Meta:
                abstract = True

        @Entity
        class ConcreteDog(AbstractDog):
            """A Dog that inherits aging and death"""
            name = field.String(required=True, unique=True, max_length=50)
            owner = field.String(required=True, max_length=15)

        immortal_dog = ConcreteDog(name='Titan', owner='God')
        assert immortal_dog is not None
        assert immortal_dog.age == 5

    def test_two_level_abstract_inheritance(self):
        """Test that abstract entities cannot be initialized"""
        @Entity
        class AbstractDog:
            """A Dog that cannot Live!"""
            age = field.Integer(default=5)

            class Meta:
                abstract = True

        @Entity
        class DogWithRecords(AbstractDog):
            """A Dog that has medical records"""
            born_at = field.DateTime(default=datetime.now())

            class Meta:
                abstract = True

        @Entity
        class ConcreteDog(DogWithRecords):
            """A Dog that inherits aging and death, with medical records"""
            name = field.String(required=True, unique=True, max_length=50)
            owner = field.String(required=True, max_length=15)

        ordinary_dog = ConcreteDog(name='Titan', owner='God')
        assert ordinary_dog is not None
        assert ordinary_dog.age == 5
        assert ordinary_dog.born_at is not None

        with pytest.raises(NotSupportedError) as exc1:
            from protean.core.repository import repo_factory
            repo_factory.register(DogWithRecords)
        assert exc1.value.args[0] == ('DogWithRecords class has been marked abstract'
                                      ' and cannot be instantiated')

    def test_reload(self):
        """Test that entities can be reloaded"""
        dog = Dog.create(id=1234, name='Johnny', owner='John')

        dog_dup = Dog.get(1234)
        assert dog_dup is not None
        assert dog_dup.id == 1234
        dog_dup.owner = 'Jane'
        dog_dup.save()

        assert dog_dup.owner == 'Jane'
        assert dog.owner == 'John'

        dog.reload()
        assert dog.owner == 'Jane'


class TestIdentity:
    """Grouping of Identity related test cases"""

    def test_default_id(self):
        """ Test that default id field is assigned when not defined"""
        @Entity
        class Dog2:
            """This is a dummy Dog Entity class without an id"""
            name = field.String(required=True, max_length=50, min_length=5)

        dog2 = Dog2(id=3, name='John Doe')
        assert dog2 is not None
        assert dog2.id == 3

    def test_non_id_identity_1(self):
        """Test that any field can be named as a primary key"""
        @Entity
        class Person:
            """This is a dummy Person Entity class with a unique SSN"""
            ssn = field.String(identifier=True, max_length=10)
            name = field.String(max_length=50)

        person = Person(ssn='134223442', name='John Doe')
        assert person.meta_.id_field.field_name == 'ssn'
        assert getattr(person, person.meta_.id_field.field_name) == '134223442'

        with pytest.raises(ValidationError):
            person = Person(name='John Doe')

    def test_non_id_identity_2(self, test_domain):
        """Test that any integer field can be named as a primary key
        and is generated automatically if not specified
        """
        @Entity
        class Person:
            """This is a dummy Person Entity class with a unique SSN"""
            ssn = field.Auto(identifier=True)
            name = field.String(max_length=50)

        test_domain.register_element(Person)

        person = Person.create(name='John Doe')
        assert person.meta_.id_field.field_name == 'ssn'
        assert person.ssn is not None

        test_domain.unregister_element(Person)


class TestEntityMetaAttributes:
    """Class that holds testcases for Entity's meta attributes"""

    def test_entity_structure(self):
        """Test the meta structure of an Entity class"""
        # Test that an entity has Meta information
        assert hasattr(Dog, 'meta_')

        meta = getattr(Dog, 'meta_')
        assert hasattr(meta, 'abstract')
        # Test that meta has correct defaults

    def test_meta_overriding_abstract(self):
        """Test that `abstract` flag can be overridden"""

        # Class with overridden meta info
        @Entity
        class Foo:
            bar = field.String(max_length=25)

            class Meta:
                abstract = True

        # Test that `abstract` is False by default
        assert getattr(Dog.meta_, 'abstract') is False

        # Test that the option in meta is overridden
        assert hasattr(Foo.meta_, 'abstract')
        assert getattr(Foo.meta_, 'abstract') is True

    def test_meta_overriding_schema_name(self):
        """Test that `schema_name` can be overridden"""

        # Class with overridden meta info
        @Entity
        class Foo:
            bar = field.String(max_length=25)

            class Meta:
                schema_name = 'foosball'

        # Test that `schema_name` is False by default
        assert getattr(Dog.meta_, 'schema_name') == 'dog'
        assert getattr(HasOneHuman1.meta_, 'schema_name') == 'has_one_human1'

        # Test that the option in meta is overridden
        assert hasattr(Foo.meta_, 'schema_name')
        assert getattr(Foo.meta_, 'schema_name') == 'foosball'

    def test_meta_overriding_provider(self):
        """Test that `provider` can be overridden"""

        # Class with overridden meta info
        @Entity
        class Foo:
            bar = field.String(max_length=25)

            class Meta:
                provider = 'non-default'

        # Test that `provider` is set to `default` by default
        assert getattr(Dog.meta_, 'provider') == 'default'

        # Test that the option in meta is overridden
        assert hasattr(Foo.meta_, 'provider')
        assert getattr(Foo.meta_, 'provider') == 'non-default'

    def test_meta_overriding_order_by(self):
        """Test that `order_by` can be overridden"""

        # Class with overridden meta info
        @Entity
        class Foo:
            bar = field.String(max_length=25)

            class Meta:
                order_by = 'bar'

        # Test that `order_by` is an empty tuple by default
        assert getattr(Dog.meta_, 'order_by') == ()

        # Test that the option in meta is overridden
        assert hasattr(Foo.meta_, 'order_by')
        assert getattr(Foo.meta_, 'order_by') == ('bar', )

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


class TestEntityHooks:
    """Test pre-save and post-save hooks defined in Entity"""

    def test_pre_save(self, test_domain):
        """Test Pre-Save Hook"""
        @Entity
        class PreSavedDog:
            """A Dog with a unique code in the universe"""
            name = field.String(required=True, unique=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)
            unique_code = field.String(max_length=255)

            def pre_save(self):
                """Perform actions before save"""
                import uuid
                self.unique_code = uuid.uuid4()

        test_domain.register_element(PreSavedDog)

        presaved_dog1 = PreSavedDog.create(name='Chucky1', owner='John')
        assert presaved_dog1.unique_code is not None

        presaved_dog2 = PreSavedDog(name='Chucky2', owner='John')
        presaved_dog2.save()
        assert presaved_dog2.unique_code is not None

        presaved_dog3 = PreSavedDog.create(name='Chucky3', owner='John')
        presaved_dog3_updated = PreSavedDog.get(presaved_dog3.id)
        presaved_dog3_updated.update(unique_code=None)
        assert presaved_dog3_updated.unique_code is not None

    def test_post_save(self, test_domain):
        """Test Post-Save Hook"""
        @Entity
        class PostSavedDog:
            """A Dog with a unique code in the universe"""
            name = field.String(required=True, unique=True, max_length=50)
            age = field.Integer(default=5)
            owner = field.String(required=True, max_length=15)
            unique_code = field.String(max_length=255)

            def post_save(self):
                """Perform actions before save"""
                import uuid
                self.unique_code = uuid.uuid4()

        test_domain.register_element(PostSavedDog)

        postsaved_dog1 = PostSavedDog.create(name='Chucky1', owner='John')
        assert postsaved_dog1.unique_code is not None
        assert postsaved_dog1.state_.is_changed is True

        postsaved_dog2 = PostSavedDog(name='Chucky2', owner='John')
        postsaved_dog2.save()
        assert postsaved_dog2.unique_code is not None
        assert postsaved_dog2.state_.is_changed is True

        postsaved_dog3 = PostSavedDog.create(name='Chucky3', owner='John')
        postsaved_dog3_updated = PostSavedDog.get(postsaved_dog3.id)
        postsaved_dog3_updated.update(unique_code=None)
        assert postsaved_dog3_updated.unique_code is not None
        assert postsaved_dog3_updated.state_.is_changed is True

        test_domain.unregister_element(PostSavedDog)
