"""
Custom Protean exception classes
"""

import logging

logger = logging.getLogger(__name__)


class ProteanException(Exception):
    """Base class for all Exceptions raised within Protean"""

    def __init__(self, messages, traceback=None, **kwargs):
        logger.debug(f"Exception:: {messages}")
        self.messages = messages
        self.traceback = traceback
        super().__init__(**kwargs)

    def __str__(self):
        return f"{dict(self.messages)}"

    def __reduce__(self):
        return (ProteanException, (self.messages,))


class NoDomainException(ProteanException):
    """Raised if a domain cannot be found or loaded in a module"""


class ConfigurationError(Exception):
    """Improper Configuration encountered like:
    * An important configuration variable is missing
    * Re-registration of Models
    * Incorrect associations
    """


class ObjectNotFoundError(ProteanException):
    """Object was not found, can raise 404"""


class TooManyObjectsError(Exception):
    """Expected one object, but found many"""


class InsufficientDataError(Exception):
    """Object was not supplied with sufficient data"""


class InvalidDataError(ProteanException):
    """Data (type, value) is invalid"""


class InvalidStateError(Exception):
    """Object is in invalid state for the given operation

    Equivalent to 409 (Conflict)"""


class InvalidOperationError(Exception):
    """Operation being performed is not permitted"""


class NotSupportedError(Exception):
    """Object does not support the operation being performed"""


class IncorrectUsageError(ProteanException):
    """Usage of a Domain Element violates principles"""


class ValidationError(ProteanException):
    """Raised when validation fails on a field. Validators and custom fields should
    raise this exception.

    :param errors: An error message or a list of error messages or a
        dictionary of error message where key is field name and value is error

    """


class SendError(Exception):
    """Raised on email dispatch failure."""


class ExpectedVersionError(Exception):
    """Raised on expected version conflicts in EventSourcing"""
