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
        self,
        messages: dict[str, list[str]],
        traceback: Optional[str] = None,
        **kwargs: Any,
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
    * Re-registration of Database Models
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


class DatabaseError(ProteanException):
    """Raised when database operations fail."""

    def __init__(self, message: str, original_exception=None, **kwargs):
        super().__init__(message, **kwargs)
        self.original_exception = original_exception


class SendError(ProteanException):
    """Raised on email dispatch failure."""


class ExpectedVersionError(ProteanException):
    """Raised on expected version conflicts in EventSourcing"""


class TransactionError(ProteanException):
    """Raised when a transaction fails to commit or encounters an error during processing"""


class DuplicateCommandError(ProteanException):
    """Raised when a command with a duplicate idempotency key is submitted
    and raise_on_duplicate=True is specified.

    Carries the original result from the first successful processing.
    """

    def __init__(self, message: str, original_result: Any = None, **kwargs):
        super().__init__(message, **kwargs)
        self.original_result = original_result


class DeserializationError(ProteanException):
    """Exception raised when message deserialization fails.

    Provides enhanced error context including message details and the original error
    to help with debugging and troubleshooting message processing issues.
    """

    def __init__(
        self, message_id: str, error: str, context: dict[str, Any] = None, **kwargs
    ):
        """Initialize DeserializationError.

        Args:
            message_id: Unique identifier of the message that failed to deserialize
            error: Description of the error that occurred
            context: Additional context information about the message and error
        """
        self.message_id = message_id
        self.error = error
        self.context = context or {}
        super().__init__(
            f"Failed to deserialize message {message_id}: {error}", **kwargs
        )

    def __repr__(self) -> str:
        return f"DeserializationError(message_id='{self.message_id}', error='{self.error}', context={self.context})"
