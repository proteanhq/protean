"""This module exposes a generic Viewset class"""
# Protean
from flask import request
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
from protean.impl.api.flask.views import GenericAPIResource


class GenericAPIResourceSet(GenericAPIResource):
    """This is a Generic View Set that has all the basic CRUD operations
    """

    show_usecase = ShowUseCase
    show_request_object = ShowRequestObject
    list_usecase = ListUseCase
    list_request_object = ListRequestObject
    create_usecase = CreateUseCase
    create_request_object = CreateRequestObject
    update_usecase = UpdateUseCase
    update_request_object = UpdateRequestObject
    delete_usecase = DeleteUseCase
    delete_request_object = DeleteRequestObject

    def get(self, identifier=None):
        """List the entities or Get by the identifier.
        """
        if identifier:
            payload = {"identifier": identifier}
            return self._process_request(
                self.show_usecase, self.show_request_object, payload=payload
            )
        else:
            return self._process_request(
                self.list_usecase,
                self.list_request_object,
                payload=request.payload,
                many=True,
            )

    def post(self):
        """Create the entity.
        """
        return self._process_request(
            self.create_usecase, self.create_request_object, payload=request.payload
        )

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
            self.update_usecase, self.update_request_object, payload=payload
        )

    def delete(self, identifier):
        """Delete the entity.
         Expected Parameters:
             identifier = <string>, identifies the entity
        """
        payload = {"identifier": identifier}
        return self._process_request(
            self.delete_usecase, self.delete_request_object, payload=payload
        )
