"""Module for defining base UseCase class"""

from abc import ABCMeta
from abc import abstractmethod

from protean.core.repository import Repository
from protean.core.exceptions import ObjectNotFoundError, \
    DuplicateObjectError, ValidationError
from protean.core.transport import ResponseFailure


class UseCase(metaclass=ABCMeta):
    """This is the base class for all UseCases"""

    def __init__(self, repo: Repository):
        """Initialize UseCase with repository factory object

        :param repo: The repository associated with the use case
        """
        self.repo = repo

    def execute(self, request_object):
        """Generic executor method of all UseCases"""

        # If the request object is not valid then return a failure response
        if not request_object.is_valid:
            return ResponseFailure.build_from_invalid_request(
                request_object)

        # Try to process the request and handle any errors encountered
        try:
            return self.process_request(request_object)

        except ValidationError as err:
            return ResponseFailure.build_unprocessable_error(
                err.normalized_messages)

        except DuplicateObjectError:
            return ResponseFailure.build_unprocessable_error(
                {'identifier': 'Object with this ID already exists.'})

        except ObjectNotFoundError:
            return ResponseFailure.build_not_found()

        except Exception as exc:  # pylint: disable=W0703
            return ResponseFailure.build_system_error(
                "{}: {}".format(exc.__class__.__name__, exc))

    @abstractmethod
    def process_request(self, request_object):
        """This method should be overridden in each UseCase"""
