"""Tests for Entity Functionality and Base Classes"""

# Standard Library Imports
from collections import OrderedDict

# Protean
import pytest

from protean import Entity
from protean.core.field.basic import String, Integer, Auto
from protean.core.exceptions import InvalidOperationError, ValidationError
from tests.old.support.dog import Dog, HasOneDog1, RelatedDog, SubDog
from tests.old.support.human import HasOneHuman1, Human


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

    def test_that_two_entities_with_same_id_are_treated_as_equal(self):
        """Test that two entities are considered equal based on their ID"""
        dog1 = Dog(id=12345, name='Slobber 1', age=6, owner='Jason')
        dog2 = Dog(id=23442, name='Slobber 2', age=6, owner='Jason')

        assert dog1 != dog2  # Because their identities are different
        assert dog2 != dog1  # Because their identities are different

        dog3 = Dog(id=12345, name='Slobber 3', age=6, owner='Jason')
        assert dog1 == dog3  # Because it's the same record even though attributes differ
        assert dog3 == dog1

    def test_that_two_entities_of_different_types_are_different_even_with_same_id(self):
        """Test that two entities are not considered equal even if they have the same ID
            and one belongs to a different Entity class
        """
        dog = Dog(id=1, name='Slobber 1', age=6, owner='Jason')
        human = Human(id=1, first_name='Jeff', last_name='Kennedy',
                      email='jeff.kennedy@presidents.com')

        assert dog != human  # Even though their identities are the same
        assert human != dog  # Even though their identities are the same

    def test_that_two_entities_of_inherited_types_are_different_even_with_same_id(self):
        """Test that two entities are not considered equal even if they have the same ID
            and one is subclassed from the other
        """
        dog = Dog(id=1, name='Slobber 1', age=6, owner='Jason')
        subdog = SubDog(id=1, name='Slobber 1', age=6, owner='Jason')

        assert dog != subdog  # Even though their identities are the same
        assert subdog != dog  # Even though their identities are the same

    def test_entity_hash(self):
        """Test that the entity's hash is based on its identity"""
        hashed_id = hash(1)

        dog = Dog(id=1, name='Slobber 1', age=6, owner='Jason')
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
            age = Integer(default=5)

        @Entity
        class Dog3(SharedEntity):
            """This is a dummy Dog Entity class with a mixin"""
            name = String(required=True, max_length=50, min_length=5)
            owner = String(required=True, max_length=15)

        dog3 = Dog3(id=3, name='John Doe', owner='Jimmy')
        assert dog3 is not None
        assert dog3.age == 5

    def test_inhertied_entity_schema(self):
        """ Test that subclasses of `Entity` can be inherited"""

        class Dog4(Dog):
            """This is a dummy Dog Entity class with a mixin"""
            pass

        assert Dog.meta_.schema_name != Dog4.meta_.schema_name

    def test_that_a_default_id_field_is_assigned_when_not_explicitly_defined(self):
        """ Test that default id field is assigned when not defined"""

        @Entity
        class Dog5:
            """This is a dummy Dog Entity class without an id"""
            name = String(required=True, max_length=50, min_length=5)

        dog5 = Dog5(id=3, name='John Doe')
        assert dog5 is not None
        assert dog5.id == 3

    def test_that_ids_are_immutable(self):
        """Test that `id` cannot be changed once assigned"""
        dog = Dog(id=4, name='Chucky', owner='John Doe')

        with pytest.raises(InvalidOperationError):
            dog.id = 5

    def test_conversion_of_entity_attributes_to_dict(self):
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

        dog2 = Dog(id=1, name='Jimmy', age=10, owner='John Doe')
        assert str(dog2) == 'Dog object (id: 1)'
        assert repr(dog2) == '<Dog: Dog object (id: 1)>'


class TestIdentity:
    """Grouping of Identity related test cases"""

    def test_default_id(self):
        """ Test that default id field is assigned when not defined"""
        @Entity
        class Dog2:
            """This is a dummy Dog Entity class without an id"""
            name = String(required=True, max_length=50, min_length=5)

        dog2 = Dog2(id=3, name='John Doe')
        assert dog2 is not None
        assert dog2.id == 3

    def test_non_id_identity_1(self):
        """Test that any field can be named as a primary key"""
        @Entity
        class Person1:
            """This is a dummy Person Entity class with a unique SSN"""
            ssn = String(identifier=True, max_length=10)
            name = String(max_length=50)

        person = Person1(ssn='134223442', name='John Doe')
        assert person.meta_.id_field.field_name == 'ssn'
        assert getattr(person, person.meta_.id_field.field_name) == '134223442'

        with pytest.raises(ValidationError):
            person = Person1(name='John Doe')

    def test_non_id_identity_2(self, test_domain):
        """Test that any integer field can be named as a primary key
        and is generated automatically if not specified
        """
        @Entity
        class Person2:
            """This is a dummy Person Entity class with a unique SSN"""
            ssn = Auto(identifier=True)
            name = String(max_length=50)

        test_domain.register_element(Person2)

        person = test_domain.get_repository(Person2).create(name='John Doe')
        assert person.meta_.id_field.field_name == 'ssn'
        assert person.ssn is not None

        test_domain.unregister_element(Person2)


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
        class Foo1:
            bar = String(max_length=25)

            class Meta:
                abstract = True

        # Test that `abstract` is False by default
        assert getattr(Dog.meta_, 'abstract') is False

        # Test that the option in meta is overridden
        assert hasattr(Foo1.meta_, 'abstract')
        assert getattr(Foo1.meta_, 'abstract') is True

    def test_meta_overriding_schema_name(self):
        """Test that `schema_name` can be overridden"""

        # Class with overridden meta info
        @Entity
        class Foo2:
            bar = String(max_length=25)

            class Meta:
                schema_name = 'foosball'

        # Test that `schema_name` is False by default
        assert getattr(Dog.meta_, 'schema_name') == 'dog'
        assert getattr(HasOneHuman1.meta_, 'schema_name') == 'has_one_human1'

        # Test that the option in meta is overridden
        assert hasattr(Foo2.meta_, 'schema_name')
        assert getattr(Foo2.meta_, 'schema_name') == 'foosball'

    def test_meta_overriding_provider(self):
        """Test that `provider` can be overridden"""

        # Class with overridden meta info
        @Entity
        class Foo3:
            bar = String(max_length=25)

            class Meta:
                provider = 'non-default'

        # Test that `provider` is set to `default` by default
        assert getattr(Dog.meta_, 'provider') == 'default'

        # Test that the option in meta is overridden
        assert hasattr(Foo3.meta_, 'provider')
        assert getattr(Foo3.meta_, 'provider') == 'non-default'

    def test_meta_overriding_order_by(self):
        """Test that `order_by` can be overridden"""

        # Class with overridden meta info
        @Entity
        class Foo4:
            bar = String(max_length=25)

            class Meta:
                order_by = 'bar'

        # Test that `order_by` is an empty tuple by default
        assert getattr(Dog.meta_, 'order_by') == ()

        # Test that the option in meta is overridden
        assert hasattr(Foo4.meta_, 'order_by')
        assert getattr(Foo4.meta_, 'order_by') == ('bar', )

    def test_meta_on_init(self):
        """Test that `meta` attribute is available after initialization"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')
        assert hasattr(dog, 'meta_')

    def test_declared_fields_normal(self):
        """Test declared fields on an entity without references"""
        dog = Dog(id=1, name='John Doe', age=10, owner='Jimmy')

        attribute_keys = list(OrderedDict(sorted(dog.meta_.attributes.items())).keys())
        assert attribute_keys == ['age', 'id', 'name', 'owner']

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
