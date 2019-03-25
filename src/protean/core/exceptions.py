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


class NotSupportedError(Exception):
    """Object does not support the operation being performed"""


class ValidationError(Exception):
    """Raised when validation fails on a field. Validators and custom fields should
    raise this exception.

    :param message: An error message or a list of error messages or a
    dictionary of error message where key is field name and value is error
    :param list field_names: Field names to store the error on. If `None`, the
     error is stored in its default location.
    """

    def __init__(self, message, field_names=None, **kwargs):
        # String, list, or dictionary of error messages.
        if not isinstance(message, dict) and not isinstance(message, list):
            messages = [message]
        else:
            messages = message
        self.messages = messages

        # List of field_names which failed validation.
        if isinstance(field_names, str):
            self.field_names = [field_names]
        else:
            self.field_names = field_names or []
        super().__init__(**kwargs)

    @property
    def normalized_messages(self, no_field_name='_entity'):
        """Return all the error messages as a dictionary"""
        if isinstance(self.messages, dict):
            return self.messages
        if not self.field_names:
            return {no_field_name: self.messages}

        return dict((name, self.messages) for name in self.field_names)


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
