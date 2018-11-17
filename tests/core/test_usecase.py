"""Tests for Usecase Functionality"""

import pytest

from protean.core.entity import Entity
from protean.core import field
from protean.core.usecase import (
    UseCase, ShowUseCase, ShowRequestObject, ListRequestObject, ListUseCase,
    CreateRequestObject, CreateUseCase, UpdateRequestObject, UpdateUseCase,
    DeleteRequestObject, DeleteUseCase)
from protean.core.repository import repo_factory as rf
from protean.impl.repository.dict_repo import RepositorySchema


class Dog(Entity):
    """This is a dummy Dog Entity class"""
    name = field.String(required=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.String(required=True, max_length=15)


class DogAutoSchema(RepositorySchema):
    """ Schema for the Dog Entity"""

    class Meta:
        """ Meta class for schema options"""
        entity = Dog
        schema_name = 'dogs-auto'


rf.register(DogAutoSchema)
repo = rf.DogAutoSchema


class TestUseCase:
    """Tests for the generic UseCase Class"""

    def test_init(self):
        """Test Initialization of the generic UseCase class"""
        with pytest.raises(TypeError):
            UseCase(repo)


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
        repo.create(name='Johnny', owner='John')

        # Build the request object and run the usecase
        request_obj = ShowRequestObject.from_dict(Dog, {'identifier': 1})
        use_case = ShowUseCase(repo)
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
        use_case = ShowUseCase(repo)
        response = use_case.execute(request_obj)
        assert response is not None
        assert not response.success

    def test_object_not_found(self):
        """Test Show Usecase for non existent object"""

        # Build the request object and run the usecase
        request_obj = ShowRequestObject.from_dict(Dog, {'identifier': 12})
        use_case = ShowUseCase(repo)
        response = use_case.execute(request_obj)
        assert response is not None
        assert not response.success


class TestListUseCase:
    """Tests for the generic ListUseCase Class"""

    @classmethod
    def setup_class(cls):
        """ Setup instructions for this case """
        repo.create(name='Murdock', owner='John', age=7)
        repo.create(name='Jean', owner='John', age=3)
        repo.create(name='Bart', owner='Carrie', age=6)

    @classmethod
    def teardown_class(cls):
        """ Teardown instructions for this case """
        repo.delete_all()

    def test_process_request(self):
        """Test List UseCase's `process_request` method"""
        # Build the request object and run the usecase
        request_obj = ListRequestObject.from_dict(
            Dog, dict(order_by=['age'], owner='John'))
        use_case = ListUseCase(repo)
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert response.success
        assert response.value.page == 1
        assert response.value.total == 3
        assert response.value.first.id == 3
        assert response.value.first.age == 3


class TestCreateUseCase:
    """Tests for the generic CreateUseCase Class"""

    def test_process_request(self):
        """Test Create UseCase's `process_request` method"""

        # Fix and rerun the usecase
        request_data = dict(name='Barry', age=10, owner='Jimmy')
        request_obj = CreateRequestObject.from_dict(Dog, request_data)
        use_case = CreateUseCase(repo)
        response = use_case.execute(request_obj)

        assert response is not None
        assert response.success
        assert response.value.id == 5
        assert response.value.name == 'Barry'

    def test_duplicate_object(self):
        """Test Create Usecase with a duplicate object"""

        # Build the request object and run the usecase
        request_data = dict(id=5, name='Barry', age=10, owner='Jimmy')
        request_obj = CreateRequestObject.from_dict(Dog, request_data)
        use_case = CreateUseCase(repo)
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert not response.success


class TestUpdateUseCase:
    """Tests for the generic UpdateUseCase Class"""

    @classmethod
    def setup_class(cls):
        """ Setup instructions for this case """
        cls.dog = repo.create(name='Johnny', owner='John')

    def test_process_request(self):
        """Test Update UseCase's `process_request` method"""

        # Build the request object and run the usecase
        request_obj = UpdateRequestObject.from_dict(
            Dog, {'identifier': self.dog.id, 'data': {'age': 13}})
        use_case = UpdateUseCase(repo)
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert response.success
        assert response.value.id == self.dog.id
        assert response.value.age == 13

    def test_validation_errors(self):
        """Test Update Usecase for validation errors"""
        # Build the request object and run the usecase
        request_obj = UpdateRequestObject.from_dict(
            Dog, {'identifier': self.dog.id, 'data': {'age': 'x'}})
        use_case = UpdateUseCase(repo)
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert not response.success
        assert response.value == {
            'code': 422, 'message': {'age': ['"x" value must be of int type.']}}


class TestDeleteUseCase:
    """Tests for the generic DeleteUseCase Class"""

    @classmethod
    def setup_class(cls):
        """ Setup instructions for this case """
        cls.dog = repo.create(name='Johnny', owner='John')

    def test_process_request(self):
        """Test Delete UseCase's `process_request` method"""

        # Build the request object and run the usecase
        request_obj = DeleteRequestObject.from_dict(
            Dog, {'identifier': self.dog.id})
        use_case = DeleteUseCase(repo)
        response = use_case.execute(request_obj)

        # Validate the response received
        assert response is not None
        assert response.success
        assert response.value is None

        # Try to lookup the object again
        request_obj = ShowRequestObject.from_dict(
            Dog, {'identifier': self.dog.id})
        use_case = ShowUseCase(repo)
        response = use_case.execute(request_obj)
        assert response is not None
        assert not response.success
