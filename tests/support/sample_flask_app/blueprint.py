""" Blueprints of the sample app"""
# Protean
from flask import Blueprint
from protean.impl.api.flask.base import Protean
from protean.impl.api.flask.views import ShowAPIResource
from protean.impl.api.flask.viewsets import GenericAPIResourceSet
from tests.support.dog import Dog
from tests.support.human import Human
from tests.support.sample_flask_app.serializers import DogSerializer, HumanSerializer
from tests.support.sample_flask_app.usecases import ListMyDogsRequestObject, ListMyDogsUsecase

blueprint = Blueprint('test_blueprint', __name__)
api_bp = Protean(blueprint)


class ShowDogResource(ShowAPIResource):
    """ View for retrieving a Dog by its ID"""
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
        response_object = self._process_request(
            ListMyDogsUsecase, ListMyDogsRequestObject, payload=payload,
            no_serialization=True)

        # Serialize the results and return the response
        serializer = DogSerializer(many=True)
        items = serializer.dump(response_object.value.items)
        result = {
            'dogs': items.data,
            'total': response_object.value.total,
            'page': response_object.value.page
        }
        return result, response_object.code.value


# Setup the routes
blueprint.add_url_rule(
    '/dogs/<int:identifier>', view_func=ShowDogResource.as_view('show_dog'),
    methods=['GET'])
api_bp.register_viewset(
    HumanResourceSet, 'humans', '/humans', pk_type='int',
    additional_routes=['/<int:identifier>/my_dogs'])
