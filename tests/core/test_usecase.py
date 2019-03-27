"""Tests for Usecase Functionality"""

import pytest
from tests.support.dog import Dog

from protean.core.usecase import CreateRequestObject
from protean.core.usecase import CreateUseCase
from protean.core.usecase import DeleteRequestObject
from protean.core.usecase import DeleteUseCase
from protean.core.usecase import ListRequestObject
from protean.core.usecase import ListUseCase
from protean.core.usecase import ShowRequestObject
from protean.core.usecase import ShowUseCase
from protean.core.usecase import UpdateRequestObject
from protean.core.usecase import UpdateUseCase
from protean.core.usecase import UseCase


class TestUseCase:
    """Tests for the generic UseCase Class"""

    def test_init(self):
        """Test Initialization of the generic UseCase class"""
        with pytest.raises(TypeError):
            UseCase()


class TestShowRequestObject:
    """Tests for the generic ShowRequest Class"""

    def test_init(self):
        """Test Initialization of the generic ShowRequest class"""
        request_obj = ShowRequestObject.from_dict(Dog, {})
        assert not request_obj.is_valid

        request_obj = ShowRequestObject.from_dict(Dog, {'identifier': 1})
        assert request_obj.is_valid
        assert request_obj.identifier == 1


class TestListRequestObject:
    """Tests for the generic ListRequest Class"""

    def test_init(self):
        """Test Initialization of the generic ListRequest class"""
        request_obj = ListRequestObject.from_dict(
            Dog, dict(page=2, order_by=['age'], owner='John'))
        assert request_obj.is_valid
        assert request_obj.page == 2
        assert request_obj.per_page == 10
        assert request_obj.order_by == ['age']
        assert request_obj.filters == {'owner': 'John'}


class TestCreateRequestObject:
    """Tests for the generic CreateRequest Class"""

    def test_init(self):
        """Test Initialization of the generic CreateRequest class"""
        request_obj = CreateRequestObject.from_dict(
            Dog, dict(id=1, name='John Doe', age=10, owner='Jimmy'))
        assert request_obj.is_valid
        assert request_obj.data == dict(
            id=1, name='John Doe', age=10, owner='Jimmy')


class TestUpdateRequestObject:
    """Tests for the generic UpdateRequest Class"""

    def test_init(self):
        """Test Initialization of the generic UpdateRequest class"""
        request_obj = UpdateRequestObject.from_dict(Dog, {'identifier': 1})
        assert not request_obj.is_valid

        request_obj = UpdateRequestObject.from_dict(
            Dog, {'identifier': 1, 'data': {'age': 13}})
        assert request_obj.is_valid
        assert request_obj.identifier == 1
        assert request_obj.data == {'age': 13}


class TestDeleteRequestObject:
    """Tests for the generic DeleteRequest Class"""

    def test_init(self):
        """Test Initialization of the generic DeleteRequest class"""
        request_obj = DeleteRequestObject.from_dict(Dog, {})
        assert not request_obj.is_valid

        request_obj = DeleteRequestObject.from_dict(Dog, {'identifier': 1})
        assert request_obj.is_valid
        assert request_obj.identifier == 1


class TestShowUseCase:
    """Tests for the generic ShowUseCase Class"""

    @classmethod
    def teardown_class(cls):
        """ Cleanup after the usecase """

    def test_process_request(self):
        """Test Show UseCase's `process_request` method"""

        # Add an object to the repository
        Dog.create(id=1, name='Johnny', owner='John')

        # Build the request object and run the usecase
        request_obj = ShowRequestObject.from_dict(Dog, {'identifier': 1})
        use_case = ShowUseCase()
        response = use_case.execute(request_obj)
        assert response is not None
        assert response.success
        assert response.value.id == 1
        assert response.value.name == 'Johnny'
        assert response.value.age == 5

    def test_invalid_request(self):
        """ Test Show Usecase with an invalid request"""

        # Build the request object and run the usecase
        request_obj = ShowRequestObject.from_dict(Dog, {})
        use_case = ShowUseCase()
        response = use_case.execute(request_obj)
        assert response is not None
        assert not response.success

    def test_object_not_found(self):
        """Test Show Usecase for non existent object"""

        # Build the request object and run the usecase
        request_obj = ShowRequestObject.from_dict(Dog, {'identifier': 12})
        use_case = ShowUseCase()
        response = use_case.execute(request_obj)
        assert response is not None
        assert not response.success


class TestListUseCase:
    """Tests for the generic ListUseCase Class"""

    def test_process_request(self):
        """Test List UseCase's `process_request` method"""
        Dog.create(name='Murdock', owner='John', age=7)
        Dog.create(name='Jean', owner='John', age=3)
        Dog.create(name='Bart', owner='Carrie', age=6)

        # Build the request object and run the usecase
        request_obj = ListRequestObject.from_dict(
            Dog, dict(order_by=['age'], owner='John'))
        use_case = ListUseCase()
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert response.success
        assert response.value.page == 1
        assert response.value.total == 2
        assert response.value.first.age == 3


class TestCreateUseCase:
    """Tests for the generic CreateUseCase Class"""

    def test_process_request(self):
        """Test Create UseCase's `process_request` method"""

        # Fix and rerun the usecase
        request_data = dict(name='Barry', age=10, owner='Jimmy')
        request_obj = CreateRequestObject.from_dict(Dog, request_data)
        use_case = CreateUseCase()
        response = use_case.execute(request_obj)

        assert response is not None
        assert response.success
        assert response.value.name == 'Barry'

    def test_unique_validation(self):
        """Test unique validation for create usecase"""

        request_data = dict(name='Drew', age=10, owner='Jimmy')
        request_obj = CreateRequestObject.from_dict(Dog, request_data)
        use_case = CreateUseCase()
        response = use_case.execute(request_obj)

        # Build the request object and run the usecase
        request_data = dict(id=response.value.id, name='Jerry', age=10, owner='Jimmy')
        request_obj = CreateRequestObject.from_dict(Dog, request_data)
        use_case = CreateUseCase()
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert not response.success
        assert response.value == {
            'code': 422,
            'message': {'id': ['`dogs` with this `id` already exists.']}}


class TestUpdateUseCase:
    """Tests for the generic UpdateUseCase Class"""

    @pytest.fixture(scope="function")
    def dog_to_update(self):
        """ Setup instructions for this case """
        dog = Dog.create(id=1, name='Johnny', owner='John')
        yield dog

    def test_process_request(self, dog_to_update):
        """Test Update UseCase's `process_request` method"""

        # Build the request object and run the usecase
        request_obj = UpdateRequestObject.from_dict(
            Dog, {'identifier': dog_to_update.id, 'data': {'age': 13}})
        use_case = UpdateUseCase()
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert response.success
        assert response.value.id == dog_to_update.id
        assert response.value.age == 13

    def test_validation_errors(self, dog_to_update):
        """Test Update Usecase for validation errors"""
        # Build the request object and run the usecase
        request_obj = UpdateRequestObject.from_dict(
            Dog, {'identifier': dog_to_update.id, 'data': {'age': 'x'}})
        use_case = UpdateUseCase()
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert not response.success
        assert response.value == {
            'code': 422, 'message': {'age': ['"x" value must be an integer.']}}

    def test_unique_validation(self, dog_to_update):
        """Test Update Usecase for unique validation"""
        # Create a dog with the same name
        Dog.create(id=2, name='Barry', owner='John')

        # Build the request object and run the usecase
        request_obj = UpdateRequestObject.from_dict(
            Dog, {'identifier': dog_to_update.id, 'data': {'name': 'Barry'}})
        use_case = UpdateUseCase()
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert not response.success
        assert response.value == {
            'code': 422,
            'message': {
                'name': ['`dogs` with this `name` already exists.']}}


class TestDeleteUseCase:
    """Tests for the generic DeleteUseCase Class"""

    @classmethod
    def setup_class(cls):
        """ Setup instructions for this case """
        cls.dog = Dog.create(name='Jimmy', owner='John')

    def test_process_request(self):
        """Test Delete UseCase's `process_request` method"""

        # Build the request object and run the usecase
        request_obj = DeleteRequestObject.from_dict(
            Dog, {'identifier': self.dog.id})
        use_case = DeleteUseCase()
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert response.success
        assert response.value is None

        # Try to lookup the object again
        request_obj = ShowRequestObject.from_dict(
            Dog, {'identifier': self.dog.id})
        use_case = ShowUseCase()
        response = use_case.execute(request_obj)
        assert response is not None
        assert not response.success
