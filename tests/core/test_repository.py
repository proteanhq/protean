"""Tests for Repository Functionality"""
from datetime import datetime

# Protean
import pytest

from protean.domain import Entity
from protean.core.entity import BaseEntity
from protean.core.exceptions import NotSupportedError, ObjectNotFoundError, ValidationError
from protean.core.field.basic import String, Integer, DateTime
from protean.core.queryset import QuerySet
from protean.core.repository.factory import repo_factory
from protean.utils.query import Q
from tests.support.dog import Dog


class TestRepository:
    """This class holds tests for Repository class"""

    def test_init(self, test_domain):
        """Test successful access to the Dog repository"""

        test_domain.get_repository(Dog).query.all()
        current_db = dict(repo_factory.get_repository(Dog).conn)
        assert current_db['data'] == {'dog': {}}

    def test_create_error(self, test_domain):
        """ Add an entity to the repository missing a required attribute"""
        with pytest.raises(ValidationError) as err:
            test_domain.get_repository(Dog).create(owner='John')

        assert err.value.normalized_messages == {'name': ['is required']}

    def test_create(self, test_domain):
        """ Add an entity to the repository"""
        dog = test_domain.get_repository(Dog).create(id=11344234, name='Johnny', owner='John')
        assert dog is not None
        assert dog.id == 11344234
        assert dog.name == 'Johnny'
        assert dog.age == 5
        assert dog.owner == 'John'

        dog = test_domain.get_repository(Dog).get(11344234)
        assert dog is not None

    def test_update(self, test_domain):
        """ Update an existing entity in the repository"""
        dog = test_domain.get_repository(Dog).create(id=2, name='Johnny', owner='Carey', age=2)

        test_domain.get_repository(Dog).update(dog, age=10)
        u_dog = test_domain.get_repository(Dog).get(2)
        assert u_dog is not None
        assert u_dog.age == 10

    def test_that_update_runs_validations(self, test_domain):
        """Try updating with invalid values"""
        dog = test_domain.get_repository(Dog).create(id=1, name='Johnny', owner='Carey', age=2)

        with pytest.raises(ValidationError):
            test_domain.get_repository(Dog).update(dog, age='x')

    def test_unique(self, test_domain):
        """ Test the unique constraints for the entity """
        test_domain.get_repository(Dog).create(id=2, name='Johnny', owner='Carey')

        with pytest.raises(ValidationError) as err:
            test_domain.get_repository(Dog).create(
                id=2, name='Johnny', owner='Carey')
        assert err.value.normalized_messages == {
            'name': ['`Dog` with this `name` already exists.']}

    def test_filter(self, test_domain):
        """ Query the repository using filters """
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = test_domain.get_repository(Dog).query.filter(owner='John')
        assert dogs is not None
        assert dogs.total == 2
        assert len(dogs.items) == 2

        # Order the results by age
        dogs = test_domain.get_repository(Dog).query.filter(owner='John').order_by('-age')
        assert dogs is not None
        assert dogs.first.age == 7
        assert dogs.first.name == 'Murdock'

    def test_result_traversal(self, test_domain):
        """ Test the traversal of the filter results"""
        for counter in range(1, 5):
            test_domain.get_repository(Dog).create(id=counter, name=counter, owner='Owner Name')

        dogs = test_domain.get_repository(Dog).query.limit(2).order_by('id')
        assert dogs is not None
        assert dogs.total == 4
        assert len(dogs.items) == 2
        assert dogs.first.id == 1
        assert dogs.has_next
        assert not dogs.has_prev

        dogs = test_domain.get_repository(Dog).query.offset(2).limit(2).order_by('id').all()
        assert len(dogs.items) == 2
        assert dogs.first.id == 3
        assert not dogs.has_next
        assert dogs.has_prev

    def test_delete(self, test_domain):
        """ Delete an object in the reposoitory by ID"""
        dog = test_domain.get_repository(Dog).create(id=3, name='Johnny', owner='Carey')
        deleted_dog = test_domain.get_repository(Dog).delete(dog)
        assert deleted_dog is not None
        assert deleted_dog.state_.is_destroyed is True

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).get(3)

    def test_delete_all(self, test_domain):
        """Delete all objects in a repository"""

        test_domain.get_repository(Dog).create(id=1, name='Athos', owner='John', age=2)
        test_domain.get_repository(Dog).create(id=2, name='Porthos', owner='John', age=3)
        test_domain.get_repository(Dog).create(id=3, name='Aramis', owner='John', age=4)
        test_domain.get_repository(Dog).create(id=4, name='dArtagnan', owner='John', age=5)

        dog_records = test_domain.get_repository(Dog).query.filter(Q())
        assert dog_records.total == 4

        test_domain.get_repository(Dog).delete_all()

        dog_records = test_domain.get_repository(Dog).query.filter(Q())
        assert dog_records.total == 0


class TestEntityLifeCycle:

    def test_get(self, test_domain):
        """Test Entity Retrieval by its primary key"""
        test_domain.get_repository(Dog).create(id=1234, name='Johnny', owner='John')

        dog = test_domain.get_repository(Dog).get(1234)
        assert dog is not None
        assert dog.id == 1234

    def test_get_object_not_found_error(self, test_domain):
        """Test failed Entity Retrieval by its primary key"""
        test_domain.get_repository(Dog).create(id=1234, name='Johnny', owner='John')

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).get(1235)

    def test_find_by(self, test_domain):
        """Test Entity retrieval by a specific column's value"""

        test_domain.get_repository(Dog).create(id=2345, name='Johnny', owner='John')

        dog = test_domain.get_repository(Dog).find_by(name='Johnny')
        assert dog is not None
        assert dog.id == 2345

    def test_find_by_object_not_found_error(self, test_domain):
        """Test Entity retrieval by specific column value(s)"""

        test_domain.get_repository(Dog).create(id=2345, name='Johnny', owner='John')

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).find_by(name='JohnnyChase')

    def test_find_by_multiple_attributes(self, test_domain):
        """Test Entity retrieval by multiple column value(s)"""

        test_domain.get_repository(Dog).create(id=2346, name='Johnny1', age=8, owner='John')
        test_domain.get_repository(Dog).create(id=2347, name='Johnny2', age=6, owner='John')

        dog = test_domain.get_repository(Dog).find_by(name='Johnny1', age=8)
        assert dog is not None
        assert dog.id == 2346

    def test_find_by_multiple_attributes_object_not_found_error(self, test_domain):
        """Test Entity retrieval by multiple column value(s)"""

        test_domain.get_repository(Dog).create(id=2346, name='Johnny1', age=8, owner='John')
        test_domain.get_repository(Dog).create(id=2347, name='Johnny2', age=6, owner='John')

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).find_by(name='Johnny1', age=6)

    def test_create_error(self, test_domain):
        """ Add an entity to the repository missing a required attribute"""
        with pytest.raises(ValidationError):
            test_domain.get_repository(Dog).create(owner='John')

    def test_create(self, test_domain):
        """ Add an entity to the repository"""
        dog = test_domain.get_repository(Dog).create(id=11344234, name='Johnny', owner='John')
        assert dog is not None
        assert dog.id == 11344234
        assert dog.name == 'Johnny'
        assert dog.age == 5
        assert dog.owner == 'John'

        dog = test_domain.get_repository(Dog).get(11344234)
        assert dog is not None

    def test_save(self, test_domain):
        """Initialize an entity and save it to repository"""
        dog = Dog(name='Johnny', owner='John')

        saved_dog = test_domain.get_repository(Dog).save(dog)
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

    def test_save_invalid_value(self):
        """Initialize an entity and save it to repository"""
        dog = Dog(name='Johnny', owner='John')

        with pytest.raises(ValidationError):
            dog.age = 'abcd'

    def test_save_again(self, test_domain):
        """Test that save can be invoked again on an already existing entity, to update values"""
        dog = Dog(name='Johnny', owner='John')
        test_domain.get_repository(Dog).save(dog)

        dog.name = 'Janey'
        test_domain.get_repository(Dog).save(dog)

        test_domain.get_repository(Dog).get(dog.id)
        assert dog.name == 'Janey'

    def test_update_with_invalid_id(self, test_domain):
        """Try to update a non-existing entry"""

        dog = test_domain.get_repository(Dog).create(id=11344234, name='Johnny', owner='John')
        test_domain.get_repository(Dog).delete(dog)
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).update(dog, {'age': 10})

    def test_update_with_dict(self, test_domain):
        """ Update an existing entity in the repository"""
        dog = test_domain.get_repository(Dog).create(id=2, name='Johnny', owner='Carey', age=2)

        test_domain.get_repository(Dog).update(dog, {'age': 10})
        u_dog = test_domain.get_repository(Dog).get(2)
        assert u_dog is not None
        assert u_dog.age == 10

    def test_update_with_kwargs(self, test_domain):
        """ Update an existing entity in the repository"""
        dog = test_domain.get_repository(Dog).create(id=2, name='Johnny', owner='Carey', age=2)

        test_domain.get_repository(Dog).update(dog, age=10)
        u_dog = test_domain.get_repository(Dog).get(2)
        assert u_dog is not None
        assert u_dog.age == 10

    def test_update_with_dict_and_kwargs(self, test_domain):
        """ Update an existing entity in the repository"""
        dog = test_domain.get_repository(Dog).create(id=2, name='Johnny', owner='Carey', age=2)

        test_domain.get_repository(Dog).update(dog, {'owner': 'Stephen'}, age=10)
        u_dog = test_domain.get_repository(Dog).get(2)
        assert u_dog is not None
        assert u_dog.age == 10
        assert u_dog.owner == 'Stephen'

    def test_that_update_runs_validations(self, test_domain):
        """Try updating with invalid values"""
        dog = test_domain.get_repository(Dog).create(id=1, name='Johnny', owner='Carey', age=2)

        with pytest.raises(ValidationError):
            test_domain.get_repository(Dog).update(dog, age='x')

    def test_update_by(self, test_domain):
        """Test that update by query updates only correct records"""
        test_domain.get_repository(Dog).create(id=1, name='Athos', owner='John', age=2)
        test_domain.get_repository(Dog).create(id=2, name='Porthos', owner='John', age=3)
        test_domain.get_repository(Dog).create(id=3, name='Aramis', owner='John', age=4)
        test_domain.get_repository(Dog).create(id=4, name='d\'Artagnan', owner='John', age=5)

        # Perform update
        updated_count = test_domain.get_repository(Dog).query.filter(age__gt=3).update(owner='Jane')

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_dog1 = test_domain.get_repository(Dog).get(1)
        u_dog2 = test_domain.get_repository(Dog).get(2)
        u_dog3 = test_domain.get_repository(Dog).get(3)
        u_dog4 = test_domain.get_repository(Dog).get(4)
        assert u_dog1.owner == 'John'
        assert u_dog2.owner == 'John'
        assert u_dog3.owner == 'Jane'
        assert u_dog4.owner == 'Jane'

    def test_update_all_with_args(self, test_domain):
        """Try updating all records satisfying filter in one step, passing a dict"""
        test_domain.get_repository(Dog).create(id=1, name='Athos', owner='John', age=2)
        test_domain.get_repository(Dog).create(id=2, name='Porthos', owner='John', age=3)
        test_domain.get_repository(Dog).create(id=3, name='Aramis', owner='John', age=4)
        test_domain.get_repository(Dog).create(id=4, name='d\'Artagnan', owner='John', age=5)

        # Perform update
        updated_count = test_domain.get_repository(Dog).query.filter(age__gt=3).update_all({'owner': 'Jane'})

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_dog1 = test_domain.get_repository(Dog).get(1)
        u_dog2 = test_domain.get_repository(Dog).get(2)
        u_dog3 = test_domain.get_repository(Dog).get(3)
        u_dog4 = test_domain.get_repository(Dog).get(4)
        assert u_dog1.owner == 'John'
        assert u_dog2.owner == 'John'
        assert u_dog3.owner == 'Jane'
        assert u_dog4.owner == 'Jane'

    def test_update_all_with_kwargs(self, test_domain):
        """Try updating all records satisfying filter in one step"""
        test_domain.get_repository(Dog).create(id=1, name='Athos', owner='John', age=2)
        test_domain.get_repository(Dog).create(id=2, name='Porthos', owner='John', age=3)
        test_domain.get_repository(Dog).create(id=3, name='Aramis', owner='John', age=4)
        test_domain.get_repository(Dog).create(id=4, name='d\'Artagnan', owner='John', age=5)

        # Perform update
        updated_count = test_domain.get_repository(Dog).query.filter(age__gt=3).update_all(owner='Jane')

        # Query and check if only the relevant records have been updated
        assert updated_count == 2

        u_dog1 = test_domain.get_repository(Dog).get(1)
        u_dog2 = test_domain.get_repository(Dog).get(2)
        u_dog3 = test_domain.get_repository(Dog).get(3)
        u_dog4 = test_domain.get_repository(Dog).get(4)
        assert u_dog1.owner == 'John'
        assert u_dog2.owner == 'John'
        assert u_dog3.owner == 'Jane'
        assert u_dog4.owner == 'Jane'

    def test_unique(self, test_domain):
        """ Test the unique constraints for the entity """
        test_domain.get_repository(Dog).create(id=2, name='Johnny', owner='Carey')

        with pytest.raises(ValidationError) as err:
            test_domain.get_repository(Dog).create(
                id=2, name='Johnny', owner='Carey')
        assert err.value.normalized_messages == {
            'name': ['`Dog` with this `name` already exists.']}

    def test_query_init(self, test_domain):
        """Test the initialization of a QuerySet"""
        query = test_domain.get_repository(Dog).query

        assert query is not None
        assert isinstance(query, QuerySet)
        assert vars(query) == vars(QuerySet(Dog))

    def test_filter_chain_initialization_from_entity(self, test_domain):
        """ Test that chaining returns a QuerySet for further chaining """
        filters = [
            test_domain.get_repository(Dog).query.filter(name='Murdock'),
            test_domain.get_repository(Dog).query.filter(name='Jean').filter(owner='John'),
            test_domain.get_repository(Dog).query.offset(1),
            test_domain.get_repository(Dog).query.limit(25),
            test_domain.get_repository(Dog).query.order_by('name'),
            test_domain.get_repository(Dog).query.exclude(name='Murdock')
        ]

        for filter in filters:
            assert isinstance(filter, QuerySet)

    def test_filter_chaining(self, test_domain):
        """ Test that chaining returns a QuerySet for further chaining """
        dog_query = test_domain.get_repository(Dog).query.filter(name='Murdock')
        filters = [
            dog_query,
            test_domain.get_repository(Dog).query.filter(name='Jean').filter(owner='John'),
            dog_query.offset(5 * 5),
            dog_query.limit(5),
            dog_query.order_by('name'),
            dog_query.exclude(name='Murdock')
        ]

        for filter in filters:
            assert isinstance(filter, QuerySet)

    def test_filter_chain_results_1(self, test_domain):
        """ Chain filter method invocations to construct a complex filter """
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(name='Jean').filter(owner='John').filter(age=3)
        dogs = query.all()

        assert dogs is not None
        assert dogs.total == 1
        assert len(dogs.items) == 1

        dog = dogs.first
        assert dog.id == 3

    def test_filter_chain_results_2(self, test_domain):
        """ Chain filter method invocations to construct a complex filter """
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John')
        dogs = query.all()

        assert dogs is not None
        assert dogs.total == 2
        assert len(dogs.items) == 2

        dog = dogs.first
        assert dog.id == 2

    def test_filter_chain_results_3(self, test_domain):
        """ Chain filter method invocations to construct a complex filter """
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by Dog attributes
        query = test_domain.get_repository(Dog).query.filter(owner='John').order_by('age')
        dogs = query.all()

        assert dogs is not None
        assert dogs.total == 2
        assert len(dogs.items) == 2

        dog = dogs.first
        assert dog.id == 3

    def test_filter_norm(self, test_domain):
        """ Query the repository using filters """
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = test_domain.get_repository(Dog).query.filter(owner='John')
        assert dogs is not None
        assert dogs.total == 2
        assert len(dogs.items) == 2

        # Order the results by age
        dogs = test_domain.get_repository(Dog).query.filter(owner='John').order_by('-age')
        assert dogs is not None
        assert dogs.first.age == 7
        assert dogs.first.name == 'Murdock'

    def test_exclude(self, test_domain):
        """Query the resository with exclusion filters"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = test_domain.get_repository(Dog).query.exclude(owner='John')
        assert dogs is not None
        assert dogs.total == 1
        assert len(dogs.items) == 1
        assert dogs.first.age == 6
        assert dogs.first.name == 'Bart'

    def test_exclude_multiple(self, test_domain):
        """Query the repository with exclusion filters"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs = test_domain.get_repository(Dog).query.exclude(name__in=['Murdock', 'Jean'])
        assert dogs is not None
        assert dogs.total == 1
        assert len(dogs.items) == 1
        assert dogs.first.age == 6
        assert dogs.first.name == 'Bart'

    def test_comparisons(self, test_domain):
        """Query with greater than operator"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='john')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        dogs_gte = test_domain.get_repository(Dog).query.filter(age__gte=3)
        dogs_lte = test_domain.get_repository(Dog).query.filter(age__lte=6)
        dogs_gt = test_domain.get_repository(Dog).query.filter(age__gt=3)
        dogs_lt = test_domain.get_repository(Dog).query.filter(age__lt=6)
        dogs_in = test_domain.get_repository(Dog).query.filter(name__in=['Jean', 'Bart', 'Nobody'])
        dogs_exact = test_domain.get_repository(Dog).query.filter(owner__exact='John')
        dogs_iexact = test_domain.get_repository(Dog).query.filter(owner__iexact='John')
        dogs_contains = test_domain.get_repository(Dog).query.filter(owner__contains='Joh')
        dogs_icontains = test_domain.get_repository(Dog).query.filter(owner__icontains='Joh')

        assert dogs_gte.total == 3
        assert dogs_lte.total == 2
        assert dogs_gt.total == 2
        assert dogs_lt.total == 1
        assert dogs_in.total == 2
        assert dogs_exact.total == 1
        assert dogs_iexact.total == 2
        assert dogs_contains.total == 1
        assert dogs_icontains.total == 2

    def test_invalid_comparison_on_query_evaluation(self, test_domain):
        """Query with an invalid/unimplemented comparison"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='john')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        with pytest.raises(NotImplementedError):
            test_domain.get_repository(Dog).query.filter(age__notexact=3).all()

    def test_result_traversal(self, test_domain):
        """ Test the traversal of the filter results"""
        for counter in range(1, 5):
            test_domain.get_repository(Dog).create(id=counter, name=counter, owner='Owner Name')

        dogs = test_domain.get_repository(Dog).query.limit(2).order_by('id')
        assert dogs.total == 4
        assert len(dogs.items) == 2
        assert dogs.first.id == 1
        assert dogs.has_next
        assert not dogs.has_prev

        dogs = test_domain.get_repository(Dog).query.offset(2).limit(2).order_by('id').all()
        assert len(dogs.items) == 2
        assert dogs.first.id == 3
        assert not dogs.has_next
        assert dogs.has_prev

    def test_delete(self, test_domain):
        """ Delete an object in the reposoitory by ID"""
        dog = test_domain.get_repository(Dog).create(id=3, name='Johnny', owner='Carey')
        deleted_dog = test_domain.get_repository(Dog).delete(dog)
        assert deleted_dog is not None
        assert deleted_dog.state_.is_destroyed is True

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).get(3)

    def test_delete_all(self, test_domain):
        """Clean up repository and delete all records"""
        test_domain.get_repository(Dog).create(id=1, name='Athos', owner='John', age=2)
        test_domain.get_repository(Dog).create(id=2, name='Porthos', owner='John', age=3)
        test_domain.get_repository(Dog).create(id=3, name='Aramis', owner='John', age=4)
        test_domain.get_repository(Dog).create(id=4, name='d\'Artagnan', owner='John', age=5)

        dogs = test_domain.get_repository(Dog).query.all()
        assert dogs.total == 4

        test_domain.get_repository(Dog).delete_all()

        dogs = test_domain.get_repository(Dog).query.all()
        assert dogs.total == 0

    def test_delete_all_by_filter(self, test_domain):
        """Try updating all records satisfying filter in one step, passing a dict"""
        test_domain.get_repository(Dog).create(id=1, name='Athos', owner='John', age=2)
        test_domain.get_repository(Dog).create(id=2, name='Porthos', owner='John', age=3)
        test_domain.get_repository(Dog).create(id=3, name='Aramis', owner='John', age=4)
        test_domain.get_repository(Dog).create(id=4, name='d\'Artagnan', owner='John', age=5)

        # Perform update
        deleted_count = test_domain.get_repository(Dog).query.filter(age__gt=3).delete_all()

        # Query and check if only the relevant records have been deleted
        assert deleted_count == 2

        dog1 = test_domain.get_repository(Dog).get(1)
        dog2 = test_domain.get_repository(Dog).get(2)

        assert dog1 is not None
        assert dog2 is not None

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).get(3)

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).get(4)

    def test_delete_by(self, test_domain):
        """Test that update by query updates only correct records"""
        test_domain.get_repository(Dog).create(id=1, name='Athos', owner='John', age=2)
        test_domain.get_repository(Dog).create(id=2, name='Porthos', owner='John', age=3)
        test_domain.get_repository(Dog).create(id=3, name='Aramis', owner='John', age=4)
        test_domain.get_repository(Dog).create(id=4, name='d\'Artagnan', owner='John', age=5)

        # Perform update
        deleted_count = test_domain.get_repository(Dog).query.filter(age__gt=3).delete()

        # Query and check if only the relevant records have been updated
        assert deleted_count == 2
        assert test_domain.get_repository(Dog).query.all().total == 2

        assert test_domain.get_repository(Dog).get(1) is not None
        assert test_domain.get_repository(Dog).get(2) is not None
        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).get(3)

        with pytest.raises(ObjectNotFoundError):
            test_domain.get_repository(Dog).get(4)

    def test_filter_returns_q_object(self, test_domain):
        """Test Negation of a criteria"""
        # Add multiple entries to the DB
        test_domain.get_repository(Dog).create(id=2, name='Murdock', age=7, owner='John')
        test_domain.get_repository(Dog).create(id=3, name='Jean', age=3, owner='John')
        test_domain.get_repository(Dog).create(id=4, name='Bart', age=6, owner='Carrie')

        # Filter by the Owner
        query = test_domain.get_repository(Dog).query.filter(owner='John')
        assert isinstance(query, QuerySet)

    def test_escaped_quotes_in_values(self, test_domain):
        """Test that escaped quotes in values are handled properly"""

        test_domain.get_repository(Dog).create(name='Athos', owner='John', age=2)
        test_domain.get_repository(Dog).create(name='Porthos', owner='John', age=3)
        test_domain.get_repository(Dog).create(name='Aramis', owner='John', age=4)

        dog1 = test_domain.get_repository(Dog).create(name="d'Artagnan1", owner='John', age=5)
        dog2 = test_domain.get_repository(Dog).create(name="d\'Artagnan2", owner='John', age=5)
        dog3 = test_domain.get_repository(Dog).create(name="d\"Artagnan3", owner='John', age=5)
        dog4 = test_domain.get_repository(Dog).create(name='d\"Artagnan4', owner='John', age=5)

        assert all(dog is not None for dog in [dog1, dog2, dog3, dog4])

    def test_abstract(self):
        """Test that abstract entities cannot be initialized"""
        @Entity
        class AbstractDog2:
            """A Dog that cannot Live!"""
            name = String(required=True, unique=True, max_length=50)
            age = Integer(default=5)
            owner = String(required=True, max_length=15)

            class Meta:
                abstract = True

        with pytest.raises(NotSupportedError) as exc1:
            from protean.core.repository.factory import repo_factory
            repo_factory.register(AbstractDog2)
        assert exc1.value.args[0] == ('AbstractDog2 class has been marked abstract'
                                      ' and cannot be instantiated')

        with pytest.raises(NotSupportedError) as exc2:
            AbstractDog2(name='Titan', age=10001, owner='God')
        assert exc2.value.args[0] == ('AbstractDog2 class has been marked abstract'
                                      ' and cannot be instantiated')

    def test_abstract_inheritance(self):
        """Test that abstract entities cannot be initialized"""
        @Entity
        class AbstractDog3:
            """A Dog that cannot Live!"""
            age = Integer(default=5)

            class Meta:
                abstract = True

        @Entity
        class ConcreteDog1(AbstractDog3):
            """A Dog that inherits aging and death"""
            name = String(required=True, unique=True, max_length=50)
            owner = String(required=True, max_length=15)

        immortal_dog = ConcreteDog1(name='Titan', owner='God')
        assert immortal_dog is not None
        assert immortal_dog.age == 5

    def test_two_level_abstract_inheritance(self):
        """Test that abstract entities cannot be initialized"""
        @Entity
        class AbstractDog:
            """A Dog that cannot Live!"""
            age = Integer(default=5)

            class Meta:
                abstract = True

        @Entity
        class DogWithRecords(AbstractDog):
            """A Dog that has medical records"""
            born_at = DateTime(default=datetime.now())

            class Meta:
                abstract = True

        @Entity
        class ConcreteDog2(DogWithRecords):
            """A Dog that inherits aging and death, with medical records"""
            name = String(required=True, unique=True, max_length=50)
            owner = String(required=True, max_length=15)

        ordinary_dog = ConcreteDog2(name='Titan', owner='God')
        assert ordinary_dog is not None
        assert ordinary_dog.age == 5
        assert ordinary_dog.born_at is not None

        with pytest.raises(NotSupportedError) as exc1:
            from protean.core.repository.factory import repo_factory
            repo_factory.register(DogWithRecords)
        assert exc1.value.args[0] == ('DogWithRecords class has been marked abstract'
                                      ' and cannot be instantiated')


class TestLookup:
    """This class holds tests for Lookup Class"""

    from protean.core.repository.lookup import BaseLookup
    from protean.impl.repository.dict_repo import DictProvider

    @DictProvider.register_lookup
    class SampleLookup(BaseLookup):
        """A simple implementation of lookup class"""
        lookup_name = "sample"

        def as_expression(self):
            return '%s %s %s' % (self.process_source(),
                                 '<<<>>>',
                                 self.process_target())

    def test_init(self):
        """Test initialization of a Lookup Object"""

        lookup = self.SampleLookup("src", "trg")
        assert lookup.as_expression() == "src <<<>>> trg"

    def test_registration(self):
        """Test registering a lookup to an adapter"""
        from protean.impl.repository.dict_repo import DictProvider

        assert DictProvider.get_lookups().get('sample') == self.SampleLookup


class TestFactory:
    """Tests for Repository Factory"""

    def test_register(self):
        """Test registering an entity to the repository factory"""
        class TempEntity(BaseEntity):
            """Temporary Entity to test registration"""
            pass

        repo_factory.register(TempEntity)

        assert repo_factory.get_entity(TempEntity.__name__) is not None

        repo_factory.unregister(TempEntity)

    def test_unregister(self):
        """Test unregistering an entity from the repository factory"""
        class TempEntity(BaseEntity):
            """Temporary Entity to test registration"""
            pass

        repo_factory.register(TempEntity)

        assert repo_factory.get_entity(TempEntity.__name__) is not None

        repo_factory.unregister(TempEntity)

        with pytest.raises(AssertionError):
            repo_factory.get_entity(TempEntity.__name__)
