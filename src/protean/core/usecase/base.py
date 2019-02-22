"""Module for defining base UseCase class"""

import logging
from abc import ABCMeta
from abc import abstractmethod

from protean.core.exceptions import ObjectNotFoundError
from protean.core.exceptions import ValidationError
from protean.core.transport import ResponseFailure

logger = logging.getLogger('protean.usecase')


class UseCase(metaclass=ABCMeta):
    """This is the base class for all UseCases"""

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

        except ObjectNotFoundError:
            return ResponseFailure.build_not_found(
                {'identifier': 'Object with this ID does not exist.'})

        except Exception as exc:
            logger.error(
                f'{self.__class__.__name__} execution failed due to error {exc}',
                exc_info=True)
            return ResponseFailure.build_system_error(
                "{}: {}".format(exc.__class__.__name__, exc))

    @abstractmethod
    def process_request(self, request_object):
        """This method should be overridden in each UseCase"""
