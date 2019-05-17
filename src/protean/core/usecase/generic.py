"""Concrete Implementations of some generic use cases"""

# Standard Library Imports
from typing import Any

# Protean
from protean.conf import active_config
from protean.core.entity import BaseEntity
from protean.core.transport import (InvalidRequestObject, BaseRequestObject, RequestObjectFactory, ResponseSuccess,
                                    ResponseSuccessCreated, ResponseSuccessWithNoContent, Status)

# Local/Relative Imports
from .base import UseCase

ShowRequestObject = RequestObjectFactory.construct(
    'ShowRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('identifier', Any, {'required': True})])


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


class ListRequestObject(BaseRequestObject):
    """
    This class encapsulates the Request Object for Listing a resource

    Possible Factory implementation:

        ListRequestObject = RequestObjectFactory.construct(
            'ListRequestObject',
            [('entity_cls', BaseEntity, {'required': True}),
            ('page', int, {'default': 1}),
            ('per_page', int),
            ('order_by', tuple),
            ('filters', dict)
            ])

    Two aspects prevent us from factory-generating this request object:
    * `filters` is usually what remains from the `dict` passed to from_dict
    * Validation - `page` cannot be less than 0
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
    def from_dict(cls, adict):
        """Initialize a ListRequestObject object from a dictionary."""
        invalid_req = InvalidRequestObject()

        if 'entity_cls' not in adict:
            invalid_req.add_error('entity_cls', 'is required')

        entity_cls = adict.pop('entity_cls', None)

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
                     .offset((request_object.page - 1) * request_object.per_page)
                     .limit(request_object.per_page)
                     .order_by(request_object.order_by)
                     .all())
        return ResponseSuccess(Status.SUCCESS, resources)


CreateRequestObject = RequestObjectFactory.construct(
    'CreateRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('data', dict, {'required': True})])


class CreateUseCase(UseCase):
    """
    This class implements the usecase for creating a new resource
    """

    def process_request(self, request_object):
        """Process Create Resource Request"""

        resource = request_object.entity_cls.create(**request_object.data)
        return ResponseSuccessCreated(resource)


UpdateRequestObject = RequestObjectFactory.construct(
    'UpdateRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('identifier', int, {'required': True}),
     ('data', dict, {'required': True})])


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


DeleteRequestObject = RequestObjectFactory.construct(
    'DeleteRequestObject',
    [('entity_cls', BaseEntity, {'required': True}),
     ('identifier', Any, {'required': True})])


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
