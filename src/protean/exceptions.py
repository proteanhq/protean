"""
Custom Protean exception classes
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ProteanException(Exception):
    """Base class for all Exceptions raised within Protean"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args)

        self.extra_info = kwargs.get("extra_info", None)

    def __reduce__(self) -> tuple[Any, tuple[Any]]:
        return (self.__class__, (self.args[0],))


class ProteanExceptionWithMessage(ProteanException):
    def __init__(
        self, messages: dict[str, str], traceback: Optional[str] = None, **kwargs: Any
    ) -> None:
        logger.debug(f"Exception:: {messages}")

        self.messages = messages
        self.traceback = traceback

        super().__init__(**kwargs)

    def __str__(self) -> str:
        return f"{dict(self.messages)}"

    def __reduce__(self) -> tuple[Any, tuple[Any]]:
        return (ProteanExceptionWithMessage, (self.messages,))


class NoDomainException(ProteanException):
    """Raised if a domain cannot be found or loaded in a module"""


class ConfigurationError(ProteanException):
    """Improper Configuration encountered like:
    * An important configuration variable is missing
    * Re-registration of Models
    * Incorrect associations
    """


class ObjectNotFoundError(ProteanException):
    """Object was not found, can raise 404"""


class TooManyObjectsError(ProteanException):
    """Expected one object, but found many"""


class InsufficientDataError(ProteanException):
    """Object was not supplied with sufficient data"""


class InvalidDataError(ProteanExceptionWithMessage):
    """Data (type, value) is invalid"""


class InvalidStateError(ProteanException):
    """Object is in invalid state for the given operation

    Equivalent to 409 (Conflict)"""


class InvalidOperationError(ProteanException):
    """Operation being performed is not permitted"""


class NotSupportedError(ProteanException):
    """Object does not support the operation being performed"""


class IncorrectUsageError(ProteanException):
    """Usage of a Domain Element violates principles"""


class ValidationError(ProteanExceptionWithMessage):
    """Raised when validation fails on a field. Validators and custom fields should
    raise this exception.

    :param errors: An error message or a list of error messages or a
        dictionary of error message where key is field name and value is error

    """


class SendError(ProteanException):
    """Raised on email dispatch failure."""


class ExpectedVersionError(ProteanException):
    """Raised on expected version conflicts in EventSourcing"""
