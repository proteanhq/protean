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

    @mock.patch('protean.core.repository.dao.BaseDAO.find_by')
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
    @mock.patch('protean.core.repository.dao.BaseDAO.exists')
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
