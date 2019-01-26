"""Concrete Implementations of some generic use cases"""

from protean.conf import active_config
from protean.core.transport import InvalidRequestObject
from protean.core.transport import ResponseSuccess
from protean.core.transport import ResponseSuccessCreated
from protean.core.transport import ResponseSuccessWithNoContent
from protean.core.transport import Status
from protean.core.transport import ValidRequestObject

from .base import UseCase


class ShowRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for retrieving a resource
    """

    def __init__(self, entity_cls, identifier=None):
        """Initialize Request Object with ID"""
        self.entity_cls = entity_cls
        self.identifier = identifier

    @classmethod
    def from_dict(cls, entity_cls, adict):
        """Initialize a ShowRequestObject object from a dictionary."""
        invalid_req = InvalidRequestObject()

        identifier = None
        if 'identifier' in adict:
            identifier = adict['identifier']
        else:
            invalid_req.add_error('identifier', 'is required')

        if invalid_req.has_errors:
            return invalid_req

        return cls(entity_cls, identifier)


class ShowUseCase(UseCase):
    """
    This class implements the usecase for retrieving a resource
    """

    def process_request(self, request_object):
        """Fetch Resource and return Entity"""

        identifier = request_object.identifier

        # Look for the object by its ID and return it
        resource = request_object.entity_cls.get(identifier)
        return ResponseSuccess(Status.SUCCESS, resource)


class ListRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for Listing a resource
    """

    def __init__(self, entity_cls, page=1, per_page=None, order_by=(),
                 filters=None):
        """Initialize Request Object with parameters"""
        self.entity_cls = entity_cls
        self.page = page
        self.per_page = per_page or active_config.PER_PAGE
        self.order_by = order_by

        if not filters:
            filters = {}
        self.filters = filters

    @classmethod
    def from_dict(cls, entity_cls, adict):
        """Initialize a ListRequestObject object from a dictionary."""
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

        # Do we need to pop out random?
        # adict.pop('random', None)

        return cls(entity_cls, page, per_page, order_by, adict)


class ListUseCase(UseCase):
    """
    This class implements the usecase for listing all resources
    """

    def process_request(self, request_object):
        """Return a list of resources"""
        resources = (request_object.entity_cls.query
                     .filter(**request_object.filters)
                     .paginate(page=request_object.page, per_page=request_object.per_page)
                     .order_by(request_object.order_by)
                     .all())
        return ResponseSuccess(Status.SUCCESS, resources)


class CreateRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for Creating New Resource
    """

    def __init__(self, entity_cls, data=None):
        """Initialize Request Object with form data"""
        self.entity_cls = entity_cls
        self.data = data

    @classmethod
    def from_dict(cls, entity_cls, adict):
        """Initialize a CreateRequestObject object from a dictionary."""
        return cls(entity_cls, adict)


class CreateUseCase(UseCase):
    """
    This class implements the usecase for creating a new resource
    """

    def process_request(self, request_object):
        """Process Create Resource Request"""

        resource = request_object.entity_cls.create(**request_object.data)
        return ResponseSuccessCreated(resource)


class UpdateRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for Updating a Resource
    """

    def __init__(self, entity_cls, identifier, data=None):
        """Initialize Request Object with form data"""
        self.entity_cls = entity_cls
        self.identifier = identifier
        self.data = data

    @classmethod
    def from_dict(cls, entity_cls, adict):
        """Initialize a UpdateRequestObject object from a dictionary."""
        invalid_req = InvalidRequestObject()

        if 'identifier' not in adict:
            invalid_req.add_error('identifier', 'Identifier is required')

        if 'data' not in adict:
            invalid_req.add_error('data', 'Data dict is required')

        if invalid_req.has_errors:
            return invalid_req

        return cls(entity_cls, adict['identifier'], adict['data'])


class UpdateUseCase(UseCase):
    """
    This class implements the usecase for updating a resource
    """

    def process_request(self, request_object):
        """Process Update Resource Request"""

        # Retrieve the object by its identifier
        entity = request_object.entity_cls.get(request_object.identifier)

        # Update the object and return the updated data
        resource = entity.update(request_object.data)
        return ResponseSuccess(Status.SUCCESS, resource)


class DeleteRequestObject(ValidRequestObject):
    """This class encapsulates the Request Object for Deleting a resource"""

    def __init__(self, entity_cls, identifier=None):
        self.entity_cls = entity_cls
        self.identifier = identifier

    @classmethod
    def from_dict(cls, entity_cls, adict):
        """Initialize a DeleteRequestObject object from a dictionary."""
        invalid_req = InvalidRequestObject()

        identifier = None
        if 'identifier' in adict:
            identifier = adict['identifier']
        else:
            invalid_req.add_error('identifier', 'is required')

        if invalid_req.has_errors:
            return invalid_req

        return cls(entity_cls, identifier)


class DeleteUseCase(UseCase):
    """
    This class implements the usecase for deleting a resource
    """

    def process_request(self, request_object):
        """Process the Delete Resource Request"""

        # Delete the object by its identifier
        entity = request_object.entity_cls.get(request_object.identifier)
        entity.delete()

        # FIXME Check for return value of `delete()`

        # We have successfully deleted the object.
        # Sending a 204 Response code.
        return ResponseSuccessWithNoContent()
