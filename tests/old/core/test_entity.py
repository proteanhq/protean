"""Tests for Entity Functionality and Base Classes"""

# Standard Library Imports
from collections import OrderedDict

# Protean
from tests.old.support.dog import HasOneDog1, RelatedDog
from tests.old.support.human import HasOneHuman1, Human


class TestEntityMetaAttributes:
    """Class that holds testcases for Entity's meta attributes"""

    def test_declared_fields_with_reference(self, test_domain):
        """Test declared fields on an entity with references"""
        human = test_domain.get_repository(Human).create(
            first_name='Jeff', last_name='Kennedy',
            email='jeff.kennedy@presidents.com')
        dog = RelatedDog(id=1, name='John Doe', age=10, owner=human)

        attribute_keys = list(OrderedDict(sorted(dog.meta_.attributes.items())).keys())
        assert attribute_keys == ['age', 'id', 'name', 'owner_id']

    def test_declared_fields_with_hasone_association(self, test_domain):
        """Test declared fields on an entity with a HasOne association"""
        human = test_domain.get_repository(HasOneHuman1).create(
            first_name='Jeff', last_name='Kennedy', email='jeff.kennedy@presidents.com')
        dog = test_domain.get_repository(HasOneDog1).create(id=1, name='John Doe', age=10, has_one_human1=human)

        assert all(key in dog.meta_.attributes for key in ['age', 'has_one_human1_id', 'id', 'name'])
        assert all(key in human.meta_.attributes for key in ['first_name', 'id', 'last_name', 'email'])
