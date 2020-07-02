"""This module exposes the Base Resource View for all Application Views"""

# Protean
import inflect

from flask import Response, current_app, request
from flask.views import MethodView
from protean.conf import active_config
from protean.core.tasklet import Tasklet
from protean.core.transport import Status
from protean.core.usecase.generic import (
    CreateRequestObject,
    CreateUseCase,
    DeleteRequestObject,
    DeleteUseCase,
    ListRequestObject,
    ListUseCase,
    ShowRequestObject,
    ShowUseCase,
    UpdateRequestObject,
    UpdateUseCase,
)
from protean.impl.api.flask.utils import immutable_dict_2_dict
from protean.utils import inflection
from protean.utils.importlib import perform_import
from werkzeug.http import parse_options_header

INFLECTOR = inflect.engine()


class APIResource(MethodView):
    """The base resource view that allows defining custom methods other than
    the standard five REST routes. Also handles rendering the output to json.

    """

    def _lookup_method(self):
        """ Lookup the class method to be called for this request"""
        func = request.url_rule.rule.rsplit("/", 1)[-1]
        meth = None
        if func and (func[0] != "<" and func[1] != ">"):
            meth = getattr(self, func, None)

        if not meth:
            meth = getattr(self, request.method.lower(), None)

        # If the request method is HEAD and we don't have a handler for it
        # retry with GET.
        if meth is None and request.method == "HEAD":
            meth = getattr(self, "get", None)

        assert meth is not None, "Unimplemented method %r" % request.method
        return meth

    def parse_payload(self):
        """ Load the data from form, json and query to `request.payload` """

        # Parse the request content based on the content type
        content_type = request.content_type or active_config.DEFAULT_CONTENT_TYPE
        mime_type, _ = parse_options_header(content_type)

        if request.method in ["POST", "PUT", "PATCH"]:
            if mime_type == "application/x-www-form-urlencoded":
                request.payload = immutable_dict_2_dict(request.form)
            elif mime_type == "multipart/form-data":
                request.payload = immutable_dict_2_dict(request.form)
                request.payload.update(immutable_dict_2_dict(request.files))
            elif mime_type == "application/json":
                request.payload = request.get_json(force=True, silent=True) or {}

        elif request.method == "GET":
            request.payload = immutable_dict_2_dict(request.args)

        # If a customer parser is defined then run that
        parser = getattr(self, "parser", None)
        if parser:
            parser = perform_import(parser)
            parser()

    def render_response(self, response):
        """ Render the response to the expected format """

        # Get the renderer to be used for this view
        renderer = getattr(self, "renderer", None)
        if not renderer:
            renderer = perform_import(active_config.DEFAULT_RENDERER)

        # Perform rendering only for non Flask Responses
        if not isinstance(response, current_app.response_class):
            data, code, headers = self._unpack_response(response)
            response = renderer(data, code, headers)

        return response

    @staticmethod
    def _unpack_response(value):
        """Return a three tuple of data, code, and headers"""
        if not isinstance(value, tuple):
            return value, 200, {}

        try:
            data, code, headers = value
            return data, code, headers
        except ValueError:
            pass

        try:
            data, code = value
            return data, code, {}
        except ValueError:
            pass

        return value, 200, {}

    def dispatch_request(self, *args, **kwargs):
        """Dispatch the request to the correct function"""

        # Lookup method defined for this resource
        meth = self._lookup_method()

        # Parse the request input and populate the payload
        self.parse_payload()

        # Call the method and create the response
        response = meth(*args, **kwargs)
        final_response = self.render_response(response)
        return final_response


class GenericAPIResource(APIResource):
    """This is the Generic Base Class for all Views
    """

    entity_cls = None
    serializer_cls = None

    def get_entity_cls(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.schema_cls`.
        """
        if not self.entity_cls:
            raise AssertionError(
                "'%s' should either include a `entity_cls` attribute, "
                "or override the `get_entity_cls()` method." % self.__class__.__name__,
            )
        return self.entity_cls

    def get_serializer(self, *args, **kwargs):
        """
        Return the serializer instance that should be used for validating and
        de-serializing input, and for serializing output.
        """
        serializer_cls = self.get_serializer_cls()
        serializer = serializer_cls(*args, **kwargs)
        serializer.context = self.get_serializer_context()
        return serializer

    def get_serializer_cls(self):
        """
        Return the class to use for the serializer.
        Defaults to using `self.serializer_class`.
        """
        if not self.serializer_cls:
            raise AssertionError(
                "'%s' should either include a `serializer_cls` attribute, "
                "or override the `get_serializer_cls()` method."
                % self.__class__.__name__,
            )
        return self.serializer_cls

    def get_serializer_context(self):
        """
        Extra context provided to the serializer class.
        """
        return {
            "view": self,
        }

    def _process_request(
        self,
        usecase_cls,
        request_object_cls,
        payload,
        many=False,
        no_serialization=False,
    ):
        """ Process the request by running the Protean Tasklet """
        # Get the schema class and derive resource name
        entity_cls = self.get_entity_cls()
        resource = inflection.underscore(entity_cls.__name__)

        # Get the serializer for this class
        serializer = None
        if not no_serialization:
            serializer = self.get_serializer(many=many)

        # Run the use case and return the results
        response_object = Tasklet.perform(
            entity_cls, usecase_cls, request_object_cls, payload, raise_error=True
        )

        # If no serialization is set just return the response object
        if no_serialization:
            return response_object.value

        # Return empty response for 204s
        if response_object.code == Status.SUCCESS_WITH_NO_CONTENT:
            return Response(None, response_object.code.value)

        # Serialize the results and return the response
        if many:
            items = serializer.dump(response_object.value.items)
            page = int(response_object.value.offset / response_object.value.limit) + 1
            result = {
                INFLECTOR.plural(resource): items.data,
                "total": response_object.value.total,
                "page": page,
            }
            return result, response_object.code.value

        else:
            result = serializer.dump(response_object.value)
            return {resource: result.data}, response_object.code.value


class ShowAPIResource(GenericAPIResource):
    """ An API view for retrieving an entity by its identifier"""

    usecase_cls = ShowUseCase
    request_object_cls = ShowRequestObject

    def get(self, identifier):
        """Show the entity.
        Expected Parameters:
             identifier = <string>, identifies the entity
        """
        payload = {"identifier": identifier}
        return self._process_request(
            self.usecase_cls, self.request_object_cls, payload=payload
        )


class ListAPIResource(GenericAPIResource):
    """ An API view for listing entities"""

    usecase_cls = ListUseCase
    request_object_cls = ListRequestObject

    def get(self):
        """List the entities.
        """
        return self._process_request(
            self.usecase_cls,
            self.request_object_cls,
            payload=request.payload,
            many=True,
        )


class CreateAPIResource(GenericAPIResource):
    """ An API view for creating an entity"""

    usecase_cls = CreateUseCase
    request_object_cls = CreateRequestObject

    def post(self):
        """Create the entity.
        """
        return self._process_request(
            self.usecase_cls, self.request_object_cls, payload=request.payload
        )


class UpdateAPIResource(GenericAPIResource):
    """ An API view for updating an entity"""

    usecase_cls = UpdateUseCase
    request_object_cls = UpdateRequestObject

    def put(self, identifier):
        """Update the entity.
         Expected Parameters:
             identifier = <string>, identifies the entity
        """
        payload = {
            "identifier": identifier,
            "data": request.payload,
        }
        return self._process_request(
            self.usecase_cls, self.request_object_cls, payload=payload
        )


class DeleteAPIResource(GenericAPIResource):
    """ An API view for deleting an entity"""

    usecase_cls = DeleteUseCase
    request_object_cls = DeleteRequestObject

    def delete(self, identifier):
        """Delete the entity.
         Expected Parameters:
             identifier = <string>, identifies the entity
        """
        payload = {"identifier": identifier}
        return self._process_request(
            self.usecase_cls, self.request_object_cls, payload=payload
        )
