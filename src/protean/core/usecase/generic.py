"""Concrete Implementations of some generic use cases"""

from protean.conf import active_config
from protean.core.transport import (
    InvalidRequestObject, ResponseSuccess, Status, ValidRequestObject,
    ResponseSuccessCreated, ResponseSuccessWithNoContent)

from .base import UseCase


class ShowRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for retrieving a resource
    """

    def __init__(self, entity, identifier=None):
        """Initialize Request Object with ID"""
        self.entity = entity
        self.identifier = identifier

    @classmethod
    def from_dict(cls, entity, adict):
        invalid_req = InvalidRequestObject()

        identifier = None
        if 'identifier' in adict:
            identifier = adict['identifier']
        else:
            invalid_req.add_error('identifier', 'is required')

        if invalid_req.has_errors:
            return invalid_req

        return cls(entity, identifier)


class ShowUseCase(UseCase):
    """
    This class implements the usecase for retrieving a resource
    """

    def process_request(self, request_object):
        """Fetch Resource and return Entity"""

        identifier = request_object.identifier

        # Look for the object by its ID and return it
        resource = self.repo.get(identifier)
        return ResponseSuccess(Status.SUCCESS, resource)


class ListRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for Listing a resource
    """

    def __init__(self, entity,
                 page=1, per_page=getattr(active_config, 'PER_PAGE', 10),
                 order_by=(), filters=None):
        """Initialize Request Object with parameters"""
        self.entity = entity
        self.page = page
        self.per_page = per_page
        self.order_by = order_by

        if not filters:
            filters = {}
        self.filters = filters

    @classmethod
    def from_dict(cls, entity, adict):
        invalid_req = InvalidRequestObject()

        # Extract the pagination parameters from the input
        page = int(adict.pop('page', 1))
        per_page = int(adict.pop(
            'per_page', getattr(active_config, 'PER_PAGE', 10)))
        order_by = adict.pop('order_by', ())

        # Check for invalid request conditions
        if page < 0:
            invalid_req.add_error('page', 'is invalid')

        if invalid_req.has_errors:
            return invalid_req

        # TODO: Do we need to pop out random?
        # adict.pop('random', None)

        return cls(entity, page, per_page, order_by, adict)


class ListUseCase(UseCase):
    """
    This class implements the usecase for listing all resources
    """

    def process_request(self, request_object):
        """Return a list of resources"""
        resources = self.repo.query(request_object.page,
                                    request_object.per_page,
                                    request_object.order_by,
                                    **request_object.filters)
        return ResponseSuccess(Status.SUCCESS, resources)


class CreateRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for Creating New Resource
    """

    def __init__(self, entity, data=None):
        """Initialize Request Object with form data"""
        self.entity = entity
        self.data = data

    @classmethod
    def from_dict(cls, entity, adict):
        return cls(entity, adict)


class CreateUseCase(UseCase):
    """
    This class implements the usecase for creating a new resource
    """

    def process_request(self, request_object):
        """Process Create Resource Request"""

        resource = self.repo.create(**request_object.data)
        return ResponseSuccessCreated(resource)


class UpdateRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for Updating a Resource
    """

    def __init__(self, entity, identifier, data=None):
        """Initialize Request Object with form data"""
        self.entity = entity
        self.identifier = identifier
        self.data = data

    @classmethod
    def from_dict(cls, entity, adict):
        invalid_req = InvalidRequestObject()

        identifier = None
        if 'identifier' in adict:
            identifier = adict.pop('identifier')
        else:
            invalid_req.add_error('identifier', 'is required')

        # Need to send some data to update, otherwise throw a 422
        if len(adict) < 1:
            invalid_req.add_error('data', 'is required')

        if invalid_req.has_errors:
            return invalid_req

        return cls(entity, identifier, adict)


class UpdateUseCase(UseCase):
    """
    This class implements the usecase for updating a resource
    """

    def process_request(self, request_object):
        """Process Update Resource Request"""

        identifier = request_object.identifier

        # Update the object and return the updated data
        resource = self.repo.update(identifier, request_object.data)
        return ResponseSuccess(Status.SUCCESS, resource)


class DeleteRequestObject(ValidRequestObject):
    """This class encapsulates the Request Object for Deleting a resource"""

    def __init__(self, entity, identifier=None):
        self.entity = entity
        self.identifier = identifier

    @classmethod
    def from_dict(cls, entity, adict):
        invalid_req = InvalidRequestObject()

        identifier = None
        if 'identifier' in adict:
            identifier = adict['identifier']
        else:
            invalid_req.add_error('identifier', 'is required')

        if invalid_req.has_errors:
            return invalid_req

        return cls(entity, identifier)


class DeleteUseCase(UseCase):
    """
    This class implements the usecase for deleting a resource
    """

    def process_request(self, request_object):
        """Process the Delete Resource Request"""

        # Delete the object by its identifier
        identifier = request_object.identifier
        self.repo.delete(identifier)

        # We have successfully deleted the object.
        # Sending a 204 Response code.
        return ResponseSuccessWithNoContent()

