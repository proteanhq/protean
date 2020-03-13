# Protean
import pytest

from protean.core.data_transfer_object import BaseDataTransferObject
from protean.core.exceptions import InvalidOperationError
from protean.core.field.basic import String
from protean.utils import fully_qualified_name

# Local/Relative Imports
from .elements import Person, PersonBasicDetails


class TestDataTransferObjectInitialization:
    def test_that_base_data_transfer_object_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseDataTransferObject()

    def test_that_a_concrete_dto_can_be_instantiated(self):
        basics = PersonBasicDetails(first_name='John', last_name='Doe', email='johndoe@gmail.com')
        assert basics is not None

    def test_that_a_concrete_dto_can_be_created_from_aggregate(self):
        full_person = Person(
            first_name='John', last_name='Doe', email='johndoe@gmail.com',
            age=34, address1='3214 Ave', city='Houston', province='TX', country='US')
        assert full_person is not None

        basics = PersonBasicDetails(first_name='John', last_name='Doe', email='johndoe@gmail.com')

        basic_info = full_person.basic_info()
        assert basic_info is not None
        assert basic_info == basics


class TestDataTransferObjectRegistration:
    def test_that_data_transfer_object_can_be_registered_with_domain(self, test_domain):
        test_domain.register(PersonBasicDetails)

        assert fully_qualified_name(PersonBasicDetails) in test_domain.data_transfer_objects

    def test_that_data_transfer_object_can_be_registered_via_annotations(self, test_domain):
        @test_domain.data_transfer_object
        class PersonAddress:
            address1 = String(max_length=255, required=True)
            address2 = String(max_length=255)
            city = String(max_length=50, required=True)
            province = String(max_length=50, required=True)
            country = String(max_length=2, required=True)

        assert fully_qualified_name(PersonAddress) in test_domain.data_transfer_objects


class TestDTOProperties:
    def test_two_DTOs_with_equal_values_are_considered_equal(self):
        person1 = PersonBasicDetails(first_name='John', last_name='Doe', email='johndoe@gmail.com')
        person2 = PersonBasicDetails(first_name='John', last_name='Doe', email='johndoe@gmail.com')

        assert person1 == person2

    @pytest.mark.xfail
    def test_that_data_transfer_objects_are_immutable(self):
        person = Person(
            first_name='John', last_name='Doe', email='johndoe@gmail.com',
            age=34, address1='3214 Ave', city='Houston', province='TX', country='US')
        with pytest.raises(InvalidOperationError):
            person.first_name = 'Mike'

    def test_output_to_dict(self):
        person = Person(
            first_name='John', last_name='Doe', email='johndoe@gmail.com',
            age=34, address1='3214 Ave', city='Houston', province='TX', country='US')
        assert person.to_dict() == {
            'id': person.id,
            'first_name': 'John', 'last_name': 'Doe', 'email': 'johndoe@gmail.com',
            'age': 34, 'address1': '3214 Ave', 'address2': None, 'city': 'Houston',
            'province': 'TX', 'country': 'US',
        }

    @pytest.mark.xfail
    def test_that_only_valid_attributes_can_be_assigned(self):
        person = PersonBasicDetails(first_name='John', last_name='Doe', email='johndoe@gmail.com')
        with pytest.raises(AttributeError):
            person.foo = 'bar'
