"""Usecases Functionality and Supporting Classes"""

import datetime
import traceback
from abc import ABCMeta
from abc import abstractmethod

from protean.config import CONFIG
from protean.repository import Repository
from protean.transport import InvalidRequestObject
from protean.transport import ResponseFailure
from protean.transport import ResponseSuccess
from protean.transport import Status
from protean.transport import ValidRequestObject


class ObjectNotFoundException(Exception):
    """This exception can be raised to indicate 404 Response codes"""


class UseCase(metaclass=ABCMeta):
    """This is the base class for all UseCases"""

    def __init__(self, repo: Repository):
        """Initialize UseCase with repository object"""
        self.repo = repo

    def execute(self, request_object):
        """Generic executor method of all UseCases"""
        if not request_object:
            return ResponseFailure.build_from_invalid_request(
                request_object)
        try:
            return self.process_request(request_object)
        except Exception as exc:  # pylint: disable=W0703
            if exc.args[0] == 404:
                return ResponseFailure.build_response(Status.NOT_FOUND, "Record does not exist")
            traceback.print_exc()
            return ResponseFailure.build_response(
                Status.SYSTEM_ERROR,
                "{}: {}".format(exc.__class__.__name__, exc))

    def _uniquify(self, request_object):
        """This method ensures that unique restraints are enforced"""

        resource = request_object.entity(**request_object.data)
        identifier = getattr(request_object, 'identifier', None)

        for item in request_object.entity._unique:  # pylint: disable=W0212
            if isinstance(item, str):
                # Is String, when the unique key is the same as DB attribute
                #   like 'preferred_term'
                db_key = key = item
            elif isinstance(item, tuple):
                # Is Tuple, when key is the same as DB attribute
                #   like 'preferred_term' and 'preferred_term.raw'
                # Tuple will be something like ('preferred_term', 'preferred_term.raw')
                key, db_key = item

            result = self.repo.find_by((db_key, getattr(resource, key)))
            if result:
                # Found a record with duplicate values
                if identifier:
                    # Is this the same record, in Update case?
                    if result.id != identifier:
                        return ResponseFailure.build_response(
                            Status.UNPROCESSABLE_ENTITY,
                            "A record with value {} already exists in another record!".format(
                                getattr(resource, key))
                        )
                else:
                    return ResponseFailure.build_response(
                        Status.UNPROCESSABLE_ENTITY,
                        "A record with value {} already exists!".format(
                            getattr(resource, key))
                    )

        return

    @abstractmethod
    def process_request(self, request_object):
        """This method should be overriddeen in each UseCase"""

        raise NotImplementedError(
            "process_request() not implemented by UseCase class")


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

        if 'identifier' in adict:
            identifier = adict['identifier']
        else:
            invalid_req.add_error('identifier', 'is required')

        if invalid_req.has_errors():
            return invalid_req

        return cls(entity, identifier)


class ShowUseCase(UseCase):
    """
    This class implements the usecase for retrieving a resource
    """

    def process_request(self, request_object):
        """Fetch Resource and return Entity"""
        identifier = request_object.identifier
        resource = self.repo.get(identifier, request_object.entity._tenant_independent)

        return ResponseSuccess(Status.SUCCESS, resource)


class ListRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for Listing a resource
    """

    def __init__(self, entity,
                 page=1, per_page=CONFIG.PER_PAGE,
                 sort=None, sort_order='desc',
                 filters=None):
        """Initialize Request Object with parameters"""
        self.entity = entity
        self.page = page
        self.per_page = per_page
        self.sort = sort
        self.sort_order = sort_order

        if not filters:
            filters = {}
        self.filters = filters

    @classmethod
    def from_dict(cls, entity, adict):
        invalid_req = InvalidRequestObject()

        page = int(adict.get('page', 1))
        per_page = int(adict.get('per_page', CONFIG.PER_PAGE))
        sort = adict.get('sort', None)
        sort_order = adict.get('sort_order', 'desc')

        if page < 0:
            invalid_req.add_error('page', 'is invalid')

        if invalid_req.has_errors():
            return invalid_req

        filters = {key: value for key, value in adict.items()
                   if key not in ['page', 'per_page', 'sort', 'sort_order']}
        filters.pop('random', None)

        return cls(entity, page, per_page, sort, sort_order, filters)


class ListUseCase(UseCase):
    """
    This class implements the usecase for listing all resources
    """

    def process_request(self, request_object):
        """Return a list of resources"""

        resources = self.repo.query(request_object.entity._tenant_independent,
                                    request_object.page,
                                    request_object.per_page,
                                    request_object.sort,
                                    request_object.sort_order,
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
        invalid_req = InvalidRequestObject()

        # Look for mandatory fields defined in the entity
        # and raise error if they are not found
        for key in entity._mandatory:  # pylint: disable=W0212
            if key not in adict:
                invalid_req.add_error(key, 'is mandatory')

        if invalid_req.has_errors():
            return invalid_req

        adict['created_at'] = datetime.datetime.utcnow()
        adict['updated_at'] = datetime.datetime.utcnow()

        return cls(entity, adict)


class CreateUseCase(UseCase):
    """
    This class implements the usecase for creating a new resource
    """

    def process_request(self, request_object):
        """Process Create Resource Request"""
        response = self._uniquify(request_object)
        if isinstance(response, ResponseFailure):
            return response

        resource = request_object.entity(**request_object.data)
        resource = self.repo.create(resource)

        if not resource:
            return ResponseFailure(resource['type'], resource['message'])

        return ResponseSuccess(Status.SUCCESS_CREATED, resource)


class UpdateRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for Updating a Resource
    """

    def __init__(self, entity, data=None):
        """Initialize Request Object with form data"""
        self.entity = entity
        self.identifier = data['identifier']
        del data['identifier']
        self.data = data

    @classmethod
    def from_dict(cls, entity, adict):
        invalid_req = InvalidRequestObject()

        if 'identifier' not in adict:
            invalid_req.add_error('identifier', 'is required')

        # Need to send some data to update, othewise throw a 422
        if len(adict) < 2:
            invalid_req.add_error('data', 'is required')

        if invalid_req.has_errors():
            return invalid_req

        adict['updated_at'] = datetime.datetime.utcnow()

        return cls(entity, adict)


class UpdateUseCase(UseCase):
    """
    This class implements the usecase for updating a resource
    """

    def process_request(self, request_object):
        """Process Update Resource Request"""
        response = self._uniquify(request_object)
        if isinstance(response, ResponseFailure):
            return response

        identifier = request_object.identifier

        resource = self.repo.update(identifier, request_object.data)

        if resource:
            return ResponseSuccess(Status.SUCCESS, resource)
        else:
            return ResponseFailure(resource['type'], resource['message'])


class DeleteRequestObject(ValidRequestObject):
    """This class encapsulates the Request Object for Deleting a resource"""

    def __init__(self, entity, identifier=None):
        self.entity = entity
        self.identifier = identifier

    @classmethod
    def from_dict(cls, entity, adict):
        invalid_req = InvalidRequestObject()
        if 'identifier' in adict:
            identifier = adict['identifier']
        else:
            invalid_req.add_error('identifier', 'is required')

        if invalid_req.has_errors():
            return invalid_req

        return cls(entity, identifier)


class DeleteUseCase(UseCase):
    """
    This class implements the usecase for deleting a resource
    """

    def process_request(self, request_object):
        identifier = request_object.identifier
        try:
            self.repo.delete(identifier)

            # We have sucessfully deleted the object. Sending a 204 Response code.
            return ResponseSuccess(Status.SUCCESS_WITH_NO_CONTENT)

        except ObjectNotFoundException:
            return ResponseFailure.build_response(Status.NOT_FOUND, request_object)
