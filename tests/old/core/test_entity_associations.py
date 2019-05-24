""" Test cases for Entity Reference field and association types """
# Protean
import mock
import pytest

from protean.core.exceptions import ValidationError
from protean.core.queryset import QuerySet
from protean.core.repository.resultset import ResultSet
from tests.old.support.dog import (
    Dog, DogRelatedByEmail, HasManyDog1, HasManyDog2, HasManyDog3,
    HasOneDog1, HasOneDog2, HasOneDog3, RelatedDog, RelatedDog2)
from tests.old.support.human import (
    HasManyHuman1, HasManyHuman2, HasManyHuman3,
    HasOneHuman1, HasOneHuman2, HasOneHuman3, Human)


class TestReference:
    """Class to test References (Foreign Key) Association"""

    def test_init(self, test_domain):
        """Test successful RelatedDog initialization"""
        human = test_domain.get_repository(Human).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
        assert dog.owner.id == human.id
        assert dog.owner_id == human.id

    def test_init_with_string_reference(self, test_domain):
        """Test successful RelatedDog initialization"""
        human = test_domain.get_repository(Human).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog2(id=1, name='John Doe', age=10, owner=human)
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
        assert dog.owner.id == human.id
        assert dog.owner_id == human.id
        assert not hasattr(human,
                           'dog')  # Reverse linkages are not provided by default

    def test_save(self, test_domain):
        """Test successful RelatedDog save"""
        human = test_domain.get_repository(Human).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
        test_domain.get_repository(RelatedDog).save(dog)
        assert dog.id is not None
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])

    def test_unsaved_entity_init(self):
        """Test that initialization fails when an unsaved entity is assigned to a relation"""
        with pytest.raises(ValueError):
            human = Human(first_name='Jeff', last_name='Kennedy',
                          email='jeff.kennedy@presidents.com')
            RelatedDog(id=1, name='John Doe', age=10, owner=human)

    def test_unsaved_entity_assign(self):
        """Test that assignment fails when an unsaved entity is assigned to a relation"""
        with pytest.raises(ValueError):
            human = Human(first_name='Jeff', last_name='Kennedy',
                          email='jeff.kennedy@presidents.com')

            dog = RelatedDog(id=1, name='John Doe', age=10)
            assert any(
                key in dog.__dict__ for key in ['owner', 'owner_id']) is False
            dog.owner = human

    def test_invalid_entity_type(self, test_domain):
        """Test that assignment fails when an invalid entity type is assigned to a relation"""
        with pytest.raises(ValidationError):
            dog = test_domain.get_repository(Dog).create(name='Johnny', owner='John')
            related_dog = RelatedDog(id=1, name='John Doe', age=10)
            related_dog.owner = dog

    def test_shadow_attribute(self, test_domain):
        """Test identifier backing the association"""
        human = test_domain.get_repository(Human).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
        assert human.id is not None
        assert dog.owner_id == human.id

    def test_save_after_assign(self, test_domain):
        """Test saving after assignment (post init)"""
        human = test_domain.get_repository(Human).create(
            id=101, first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10)
        assert any(
            key in dog.__dict__ for key in ['owner', 'owner_id']) is False
        dog.owner = human
        test_domain.get_repository(RelatedDog).save(dog)
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
        assert dog.owner_id == human.id

    def test_fetch_after_save(self, test_domain):
        """Test fetch after save and ensure reference is not auto-loaded"""
        human = test_domain.get_repository(Human).create(
            id=101, first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10)
        dog.owner = human
        test_domain.get_repository(RelatedDog).save(dog)

        dog2 = test_domain.get_repository(RelatedDog).get(dog.id)
        # Reference attribute is not loaded automatically
        assert 'owner' not in dog2.__dict__
        assert dog2.owner_id == human.id

        # Accessing attribute shows it up in __dict__
        getattr(dog2, 'owner')
        assert 'owner' in dog2.__dict__

    def test_shadow_attribute_init(self, test_domain):
        """Test identifier backing the association"""
        human = test_domain.get_repository(Human).create(
            id=101, first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner_id=human.id)
        assert 'owner_id' in dog.__dict__
        assert 'owner' not in dog.__dict__
        test_domain.get_repository(RelatedDog).save(dog)
        assert dog.owner_id == human.id
        assert dog.owner.id == human.id
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])

    def test_shadow_attribute_assign(self, test_domain):
        """Test identifier backing the association"""
        human = test_domain.get_repository(Human).create(
            id=101, first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10)
        dog.owner_id = human.id
        assert 'owner' not in dog.__dict__
        test_domain.get_repository(RelatedDog).save(dog)
        assert dog.owner_id == human.id
        assert dog.owner.id == human.id
        assert 'owner' in dog.__dict__

    def test_reference_reset_association_to_None(self, test_domain):
        """Test that the reference field and shadow attribute are reset together"""
        human = test_domain.get_repository(Human).create(
            id=101, first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
        assert dog.owner_id == human.id
        assert dog.owner.id == human.id

        dog.owner = None
        assert any(
            key in dog.__dict__ for key in ['owner', 'owner_id']) is False
        assert dog.owner is None
        assert dog.owner_id is None

    def test_reference_reset_shadow_field_to_None(self, test_domain):
        """Test that the reference field and shadow attribute are reset together"""
        human = test_domain.get_repository(Human).create(
            id=101, first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
        assert dog.owner_id == human.id
        assert dog.owner.id == human.id

        dog.owner_id = None
        assert any(
            key in dog.__dict__ for key in ['owner', 'owner_id']) is False
        assert dog.owner is None
        assert dog.owner_id is None

    def test_reference_reset_association_by_del(self, test_domain):
        """Test that the reference field and shadow attribute are reset together"""
        human = test_domain.get_repository(Human).create(
            id=101, first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
        assert dog.owner_id == human.id
        assert dog.owner.id == human.id

        del dog.owner
        assert any(
            key in dog.__dict__ for key in ['owner', 'owner_id']) is False
        assert dog.owner is None
        assert dog.owner_id is None

    def test_reference_reset_shadow_field_by_del(self, test_domain):
        """Test that the reference field and shadow attribute are reset together"""
        human = test_domain.get_repository(Human).create(
            id=101, first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
        assert dog.owner_id == human.id
        assert dog.owner.id == human.id

        del dog.owner_id
        assert any(
            key in dog.__dict__ for key in ['owner', 'owner_id']) is False
        assert dog.owner is None
        assert dog.owner_id is None

    def test_via(self, test_domain):
        """Test successful save with an entity linked by via"""
        human = test_domain.get_repository(Human).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = test_domain.get_repository(DogRelatedByEmail).create(
            id=1, name='John Doe', age=10, owner=human)
        assert all(key in dog.__dict__ for key in ['owner', 'owner_email'])
        assert hasattr(dog, 'owner_email')
        assert dog.owner_email == human.email

    def test_via_with_shadow_attribute_assign(self, test_domain):
        """Test successful save with an entity linked by via"""
        human = test_domain.get_repository(Human).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = DogRelatedByEmail(id=1, name='John Doe', age=10)
        dog.owner_email = human.email
        assert 'owner' not in dog.__dict__
        test_domain.get_repository(DogRelatedByEmail).save(dog)
        assert hasattr(dog, 'owner_email')
        assert dog.owner_email == human.email

    @mock.patch('protean.core.repository.base.AbstractRepository.find_by')
    def test_caching(self, find_by_mock, test_domain):
        """Test that subsequent accesses after first retrieval don't fetch record again"""
        human = test_domain.get_repository(Human).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner_id=human.id)

        for _ in range(3):
            getattr(dog, 'owner')
        assert find_by_mock.call_count == 1


class TestHasOne:
    """Class to test HasOne Association"""

    def test_init(self, test_domain):
        """Test successful HasOne initialization"""
        human = test_domain.get_repository(HasOneHuman1).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = test_domain.get_repository(HasOneDog1).create(
            id=101, name='John Doe', age=10,
            has_one_human1=human)
        assert dog.has_one_human1 == human
        assert human.dog.id == dog.id

    def test_init_with_via(self, test_domain):
        """Test successful HasOne initialization with a class containing via"""
        human = test_domain.get_repository(HasOneHuman2).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = test_domain.get_repository(HasOneDog2).create(id=101, name='John Doe', age=10, human=human)
        assert dog.human == human
        assert 'dog' not in human.__dict__
        assert human.dog.id == dog.id
        assert 'dog' in human.__dict__

    def test_init_with_no_reference(self, test_domain):
        """Test successful HasOne initialization with a class containing via"""
        human = test_domain.get_repository(HasOneHuman3).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = test_domain.get_repository(HasOneDog3).create(
            id=101, name='John Doe', age=10, human_id=human.id)
        assert dog.human_id == human.id
        assert not hasattr(dog, 'human')
        assert 'human' not in dog.__dict__
        assert human.dog.id == dog.id

    @mock.patch('protean.core.repository.base.AbstractRepository.find_by')
    def test_caching(self, find_by_mock, test_domain):
        """Test that subsequent accesses after first retrieval don't fetch record again"""
        human = test_domain.get_repository(HasOneHuman3).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        test_domain.get_repository(HasOneDog3).create(id=101, name='John Doe', age=10, human_id=human.id)

        for _ in range(3):
            getattr(human, 'dog')
        assert find_by_mock.call_count == 1


class TestHasMany:
    """Class to test HasMany Association"""

    def test_init(self, test_domain):
        """Test successful HasOne initialization"""
        human = test_domain.get_repository(HasManyHuman1).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog1 = test_domain.get_repository(HasManyDog1).create(
            id=101, name='John Doe', age=10, has_many_human1=human)
        dog2 = test_domain.get_repository(HasManyDog1).create(
            id=102, name='Jane Doe', age=10, has_many_human1=human)

        assert dog1.has_many_human1.id == human.id
        assert dog2.has_many_human1.id == human.id
        assert 'dogs' not in human.__dict__
        assert len(human.dogs) == 2
        assert 'dogs' in human.__dict__  # Avaiable after access

        assert isinstance(human.dogs, QuerySet)
        assert isinstance(human.dogs.all(), ResultSet)
        assert all(dog.id in [101, 102] for dog in human.dogs)  # `__iter__` magic here

    def test_init_with_via(self, test_domain):
        """Test successful HasMany initialization with a class containing via"""
        human = test_domain.get_repository(HasManyHuman2).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog1 = test_domain.get_repository(HasManyDog2).create(id=101, name='John Doe', age=10, human=human)
        dog2 = test_domain.get_repository(HasManyDog2).create(id=102, name='Jane Doe', age=10, human=human)

        assert dog1.human.id == human.id
        assert dog2.human.id == human.id

        assert len(human.dogs) == 2

    def test_init_with_no_reference(self, test_domain):
        """Test successful HasOne initialization with a class containing via"""
        human = test_domain.get_repository(HasManyHuman3).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog1 = test_domain.get_repository(HasManyDog3).create(
            id=101, name='John Doe', age=10, human_id=human.id)

        assert dog1.human_id == human.id
        assert not hasattr(dog1, 'human')

    @mock.patch('protean.core.queryset.QuerySet.filter')
    @mock.patch('protean.core.repository.base.AbstractRepository.exists')
    def test_caching(self, exists_mock, filter_mock, test_domain):
        """Test that subsequent accesses after first retrieval don't fetch record again"""
        exists_mock.return_value = False
        human = test_domain.get_repository(HasManyHuman3).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        test_domain.get_repository(HasManyDog3).create(id=101, name='John Doe', human_id=human.id)
        test_domain.get_repository(HasManyDog3).create(id=102, name='Jane Doe', human_id=human.id)
        test_domain.get_repository(HasManyDog3).create(id=103, name='Jinny Doe', human_id=human.id)

        for _ in range(3):
            getattr(human, 'dogs')
        assert filter_mock.call_count == 1
