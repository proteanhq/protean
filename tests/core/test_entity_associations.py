""" Test cases for Entity Reference field and association types """
import mock
import pytest
from tests.support.dog import Dog
from tests.support.dog import DogRelatedByEmail
from tests.support.dog import HasManyDog1
from tests.support.dog import HasManyDog2
from tests.support.dog import HasManyDog3
from tests.support.dog import HasOneDog1
from tests.support.dog import HasOneDog2
from tests.support.dog import HasOneDog3
from tests.support.dog import RelatedDog
from tests.support.dog import RelatedDog2
from tests.support.human import HasManyHuman1
from tests.support.human import HasManyHuman2
from tests.support.human import HasManyHuman3
from tests.support.human import HasOneHuman1
from tests.support.human import HasOneHuman2
from tests.support.human import HasOneHuman3
from tests.support.human import Human

from protean.core.exceptions import ValidationError


class TestReference:
    """Class to test References (Foreign Key) Association"""

    def test_init(self):
        """Test successful RelatedDog initialization"""
        human = Human.create(first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
        assert dog.owner.id == human.id
        assert dog.owner_id == human.id

    def test_init_with_string_reference(self):
        """Test successful RelatedDog initialization"""
        human = Human.create(first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = RelatedDog2(id=1, name='John Doe', age=10, owner=human)
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
        assert dog.owner.id == human.id
        assert dog.owner_id == human.id
        assert not hasattr(human,
                           'dog')  # Reverse linkages are not provided by default

    def test_save(self):
        """Test successful RelatedDog save"""
        human = Human.create(first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
        dog.save()
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
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
        assert human.id is not None
        assert dog.owner_id == human.id

    def test_save_after_assign(self):
        """Test saving after assignment (post init)"""
        human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10)
        assert any(
            key in dog.__dict__ for key in ['owner', 'owner_id']) is False
        dog.owner = human
        dog.save()
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])
        assert dog.owner_id == human.id

    def test_fetch_after_save(self):
        """Test fetch after save and ensure reference is not auto-loaded"""
        human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10)
        dog.owner = human
        dog.save()

        dog2 = RelatedDog.get(dog.id)
        # Reference attribute is not loaded automatically
        assert 'owner' not in dog2.__dict__
        assert dog2.owner_id == human.id

        # Accessing attribute shows it up in __dict__
        getattr(dog2, 'owner')
        assert 'owner' in dog2.__dict__

    def test_shadow_attribute_init(self):
        """Test identifier backing the association"""
        human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner_id=human.id)
        assert 'owner_id' in dog.__dict__
        assert 'owner' not in dog.__dict__
        dog.save()
        assert dog.owner_id == human.id
        assert dog.owner.id == human.id
        assert all(key in dog.__dict__ for key in ['owner', 'owner_id'])

    def test_shadow_attribute_assign(self):
        """Test identifier backing the association"""
        human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10)
        dog.owner_id = human.id
        assert 'owner' not in dog.__dict__
        dog.save()
        assert dog.owner_id == human.id
        assert dog.owner.id == human.id
        assert 'owner' in dog.__dict__

    def test_reference_reset_association_to_None(self):
        """Test that the reference field and shadow attribute are reset together"""
        human = Human.create(id=101, first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)
        assert dog.owner_id == human.id
        assert dog.owner.id == human.id

        dog.owner = None
        assert any(
            key in dog.__dict__ for key in ['owner', 'owner_id']) is False
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
        assert any(
            key in dog.__dict__ for key in ['owner', 'owner_id']) is False
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
        assert any(
            key in dog.__dict__ for key in ['owner', 'owner_id']) is False
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
        assert any(
            key in dog.__dict__ for key in ['owner', 'owner_id']) is False
        assert dog.owner is None
        assert dog.owner_id is None

    def test_via(self):
        """Test successful save with an entity linked by via"""
        human = Human.create(first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = DogRelatedByEmail.create(id=1, name='John Doe', age=10,
                                       owner=human)
        assert all(key in dog.__dict__ for key in ['owner', 'owner_email'])
        assert hasattr(dog, 'owner_email')
        assert dog.owner_email == human.email

    def test_via_with_shadow_attribute_assign(self):
        """Test successful save with an entity linked by via"""
        human = Human.create(first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = DogRelatedByEmail(id=1, name='John Doe', age=10)
        dog.owner_email = human.email
        assert 'owner' not in dog.__dict__
        dog.save()
        assert hasattr(dog, 'owner_email')
        assert dog.owner_email == human.email

    @mock.patch('protean.core.entity.Entity.find_by')
    def test_caching(self, find_by_mock):
        """Test that subsequent accesses after first retrieval don't fetch record again"""
        human = Human.create(first_name='Jeff', last_name='Kennedy',
                             email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner_id=human.id)

        for _ in range(3):
            getattr(dog, 'owner')
        assert find_by_mock.call_count == 1


class TestHasOne:
    """Class to test HasOne Association"""

    def test_init(self):
        """Test successful HasOne initialization"""
        human = HasOneHuman1.create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = HasOneDog1.create(id=101, name='John Doe', age=10,
                                has_one_human1=human)
        assert dog.has_one_human1 == human
        assert human.dog.id == dog.id

    def test_init_with_via(self):
        """Test successful HasOne initialization with a class containing via"""
        human = HasOneHuman2.create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = HasOneDog2.create(id=101, name='John Doe', age=10, human=human)
        assert dog.human == human
        assert 'dog' not in human.__dict__
        assert human.dog.id == dog.id
        assert 'dog' in human.__dict__

    def test_init_with_no_reference(self):
        """Test successful HasOne initialization with a class containing via"""
        human = HasOneHuman3.create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = HasOneDog3.create(id=101, name='John Doe', age=10,
                                human_id=human.id)
        assert dog.human_id == human.id
        assert not hasattr(dog, 'human')
        assert 'human' not in dog.__dict__
        assert human.dog.id == dog.id

    @mock.patch('protean.core.entity.Entity.find_by')
    def test_caching(self, find_by_mock):
        """Test that subsequent accesses after first retrieval don't fetch record again"""
        human = HasOneHuman3.create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        HasOneDog3.create(id=101, name='John Doe', age=10, human_id=human.id)

        for _ in range(3):
            getattr(human, 'dog')
        assert find_by_mock.call_count == 1


class TestHasMany:
    """Class to test HasMany Association"""

    def test_init(self):
        """Test successful HasOne initialization"""
        human = HasManyHuman1.create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog1 = HasManyDog1.create(id=101, name='John Doe', age=10,
                                  has_many_human1=human)
        dog2 = HasManyDog1.create(id=102, name='Jane Doe', age=10,
                                  has_many_human1=human)

        assert dog1.has_many_human1.id == human.id
        assert dog2.has_many_human1.id == human.id
        assert 'dogs' not in human.__dict__
        assert len(human.dogs) == 2
        assert 'dogs' in human.__dict__  # Avaiable after access

    def test_init_with_via(self):
        """Test successful HasMany initialization with a class containing via"""
        human = HasManyHuman2.create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog1 = HasManyDog2.create(id=101, name='John Doe', age=10, human=human)
        dog2 = HasManyDog2.create(id=102, name='Jane Doe', age=10, human=human)

        assert dog1.human.id == human.id
        assert dog2.human.id == human.id

        assert len(human.dogs) == 2

    def test_init_with_no_reference(self):
        """Test successful HasOne initialization with a class containing via"""
        human = HasManyHuman3.create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog1 = HasManyDog3.create(id=101, name='John Doe', age=10,
                                  human_id=human.id)

        assert dog1.human_id == human.id
        assert not hasattr(dog1, 'human')

    @mock.patch('protean.core.entity.QuerySet.filter')
    @mock.patch('protean.core.entity.Entity.exists')
    def test_caching(self, exists_mock, filter_mock):
        """Test that subsequent accesses after first retrieval don't fetch record again"""
        exists_mock.return_value = False
        human = HasManyHuman3.create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        HasManyDog3.create(id=101, name='John Doe', human_id=human.id)
        HasManyDog3.create(id=102, name='Jane Doe', human_id=human.id)
        HasManyDog3.create(id=103, name='Jinny Doe', human_id=human.id)

        for _ in range(3):
            getattr(human, 'dogs')
        assert filter_mock.call_count == 1
