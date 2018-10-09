"""
Custom Protean exception classes
"""


class ConfigurationError(Exception):
    """An important configuration variable is missing"""


class ObjectNotFoundError(Exception):
    """Object was not found, can raise 404"""


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
