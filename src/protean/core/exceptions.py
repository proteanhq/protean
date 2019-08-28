"""
Custom Protean exception classes
"""


class ConfigurationError(Exception):
    """Improper Configuration encountered like:
        * An important configuration variable is missing
        * Re-registration of Models
        * Incorrect associations
    """


class ObjectNotFoundError(Exception):
    """Object was not found, can raise 404"""


class TooManyObjectsError(Exception):
    """Expected one object, but found many"""


class InvalidStateError(Exception):
    """Object is in invalid state for the given operation"""


class InvalidOperationError(Exception):
    """Operation being performed is not permitted"""


class NotSupportedError(Exception):
    """Object does not support the operation being performed"""


class IncorrectUsageError(Exception):
    """Usage of a Domain Element violates principles"""


class ValidationError(Exception):
    """Raised when validation fails on a field. Validators and custom fields should
    raise this exception.

    :param errors: An error message or a list of error messages or a
    dictionary of error message where key is field name and value is error
    """

    def __init__(self, messages, **kwargs):
        self.messages = messages
        super().__init__(**kwargs)


class UsecaseExecutionError(Exception):
    """ Raised when a failure response is encountered on executing a usecase

    :param value: a tuple comprising of the error code and error message
    :type value: tuple
    :param orig_exc: Optional original exception raised in the usecase
    :param orig_trace: Optional trace of the original exception in the usecase
    """

    def __init__(self, value, orig_exc=None, orig_trace=None, **kwargs):
        self.value = value
        self.orig_exc = orig_exc
        self.orig_trace = orig_trace

        super().__init__(**kwargs)
