""" Views of the sample app"""
# Protean
from protean.context import context
from protean.impl.api.flask.views import (APIResource, CreateAPIResource, DeleteAPIResource,
                                          ListAPIResource, ShowAPIResource, UpdateAPIResource)
from protean.impl.api.flask.viewsets import GenericAPIResourceSet
from tests.support.dog import Dog
from tests.support.human import Human

# Local/Relative Imports
from .serializers import DogSerializer, HumanSerializer
from .usecases import ListMyDogsRequestObject, ListMyDogsUsecase


class ShowDogResource(ShowAPIResource):
    """ View for retrieving a Dog by its ID"""
    entity_cls = Dog
    serializer_cls = DogSerializer


class ListDogResource(ListAPIResource):
    """ View for listing Dog entities"""
    entity_cls = Dog
    serializer_cls = DogSerializer


class CreateDogResource(CreateAPIResource):
    """ View for creating a Dog Entity"""
    entity_cls = Dog
    serializer_cls = DogSerializer


class UpdateDogResource(UpdateAPIResource):
    """ View for updating a Dog by its ID"""
    entity_cls = Dog
    serializer_cls = DogSerializer


class DeleteDogResource(DeleteAPIResource):
    """ View for deleting a Dog by its ID"""
    entity_cls = Dog
    serializer_cls = DogSerializer


class HumanResourceSet(GenericAPIResourceSet):
    """ Resource Set for the Human Entity"""
    entity_cls = Human
    serializer_cls = HumanSerializer

    def my_dogs(self, identifier):
        """ List all the dogs belonging to the Human"""
        # Run the usecase and get the related dogs
        payload = {'identifier': identifier}
        dogs_list = self._process_request(
            ListMyDogsUsecase, ListMyDogsRequestObject, payload=payload,
            no_serialization=True)

        # Serialize the results and return the response
        serializer = DogSerializer(many=True)
        items = serializer.dump(dogs_list.items)
        page = int(dogs_list.offset / dogs_list.limit) + 1
        result = {
            'dogs': items.data,
            'total': dogs_list.total,
            'page': page
        }
        return result, 200


def flask_view():
    """ A non protean flask view """
    return 'View Response', 200


class CurrentContextResource(APIResource):
    """ View for retrieving the current context information """

    def get(self):
        """ Return the context information on GET """
        context_data = {
            'host_url': context.host_url,
            'url': context.url,
            'tenant_id': context.tenant_id,
            'user_agent': context.user_agent,
            'user_agent_hash': context.user_agent_hash,
            'remote_addr': context.remote_addr
        }
        return context_data
