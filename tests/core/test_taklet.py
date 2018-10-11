"""Tests for Tasklet Functionality"""

from protean.core.tasklet import Tasklet
from protean.core.usecase import ShowRequestObject, ShowUseCase, CreateUseCase, \
    CreateRequestObject
from protean.core.entity import Entity
from protean.core import field

from .test_usecase import DogSchema
from ..support.dict_repo import drf, DictSchema, DictRepository


class AppTasklet(Tasklet):

    @classmethod
    def get_context_data(cls):
        return {'user': 'admin'}


class Dog2(Entity):
    """This is a dummy Dog Entity class"""
    id = field.Integer(identifier=True)
    name = field.String(required=True, max_length=50)
    age = field.Integer(default=5)
    owner = field.String(required=True, max_length=15)
    created_by = field.String(required=True, max_length=15)


class Dog2Schema(DictSchema):
    """ Schema for the Dog2 Entity"""

    class Meta:
        """ Meta class for schema options"""
        entity = Dog2
        schema_name = 'dogs2'


drf.register(DictRepository, Dog2Schema)


class CreateUseCase2(CreateUseCase):
    """ Updated Create use case to handle context """
    def process_request(self, request_object):
        """Process Create Resource Request"""

        request_object.data['created_by'] = self.context['user']
        return super().process_request(request_object)


class TestTasklet:
    """Tests for Tasklet Utility Methods"""

    def test_perform(self):
        """Test call to Tasklet's perform method"""

        # Perform a Show Usecase using Tasklet
        payload = {'identifier': 2}
        response = Tasklet.perform(
            drf, DogSchema, ShowUseCase, ShowRequestObject, payload)

        # Validate the response received
        assert response is not None
        assert response.success
        assert response.value.id == 2
        assert response.value.name == 'Murdock'

    def test_context(self):
        """ Test context information is passed to use cases"""

        # Perform a Create Usecase using Tasklet
        payload = dict(id=1, name='Jerry', age=10, owner='Jack')
        response = AppTasklet.perform(
            drf, Dog2Schema, CreateUseCase2, CreateRequestObject, payload)

        # Validate the response received
        assert response is not None
        assert response.success
        assert response.value.id == 1
        assert response.value.name == 'Jerry'
        assert response.value.created_by == 'admin'
