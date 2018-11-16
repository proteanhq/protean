"""Module for defining base Field class"""

from abc import ABCMeta, abstractmethod
from typing import Union, Iterable, Callable, Any

from protean.core import exceptions


MISSING_ERROR_MESSAGE = (
    'ValidationError raised by `{class_name}`, but error key `{key}` does '
    'not exist in the `error_messages` dictionary.'
)


class Field(metaclass=ABCMeta):
    """Abstract field from which other fields should extend.

    :param default: If set, this value will be used during entity loading
    if the field value is missing.
    :param required: if `True`, Raise a :exc:`ValidationError` if the field
    value is `None`.
    :param validators: Optional list of validators to be applied for this field.

    """

    # Default error messages for various kinds of errors.
    default_error_messages = {
        'invalid_type': 'Value is not of the valid type for this field.',
        'required': 'This field is required.',
    }

    # Default validators for a Field
    default_validators = []

    # These values will trigger the self.required check.
    empty_values = (None, '', [], (), {})

    def __init__(self, identifier: bool = False, default: Any = None,
                 required: bool = False, label: str = None,
                 validators: Iterable = (), error_messages: dict = None):

        self.identifier = identifier
        self.default = default

        # Make identifier fields as required
        self.required = True if self.identifier else required
        self.label = label
        self._validators = validators

        # These are set up by `.bind()` when the field is added to a serializer.
        self.field_name = None

        # Collect default error message from self and parent classes
        messages = {}
        for cls in reversed(self.__class__.__mro__):
            messages.update(getattr(cls, 'default_error_messages', {}))
        messages.update(error_messages or {})
        self.error_messages = messages

    def bind(self, field_name):
        """
        Initializes the field name for the field instance.
        Called when a field is added to the parent entity instance.
        """

        self.field_name = field_name

        # `self.label` should default to being based on the field name.
        if self.label is None:
            self.label = field_name.replace('_', ' ').capitalize()

    def fail(self, key, **kwargs):
        """A helper method that simply raises a `ValidationError`.
        """
        try:
            msg = self.error_messages[key]
        except KeyError:
            class_name = self.__class__.__name__
            msg = MISSING_ERROR_MESSAGE.format(class_name=class_name,
                                               key=key)
            raise AssertionError(msg)
        if isinstance(msg, str):
            msg = msg.format(**kwargs)

        raise exceptions.ValidationError(msg, self.field_name)

    @property
    def validators(self):
        """
        Some validators can't be created at field initialization time.
        This method provides a way to handle such default validators.
        """
        return [*self.default_validators, *self._validators]

    @abstractmethod
    def _validate_type(self, value: Any):
        """
        Abstract method to validate the type of the value passed.
        All subclasses must implement this method.
        Raise a :exc:`ValidationError` if validation does not succeed.
        """
        pass

    def _run_validators(self, value):
        """Perform validation on ``value``. Raise a :exc:`ValidationError` if
        validation does not succeed.
        """
        if value in self.empty_values:
            return

        errors = []
        for validator in self.validators:
            try:
                validator(value)
            except exceptions.ValidationError as err:
                if isinstance(err.messages, dict):
                    errors.append(err.messages)
                else:
                    errors.extend(err.messages)

        if errors:
            raise exceptions.ValidationError(errors)

    def load(self, value: Any):
        """
        Load the value for the field, run validators and return the value.
        Subclasses can override this to provide custom load logic.

        :param value: value of the field

        """

        if value in self.empty_values:
            # If a default has been set for the field return it
            if self.default:
                default = self.default
                value = default() if callable(default) else default
                return value

            # If no default is set and this field is required
            elif self.required:
                self.fail('required')

            # In all other cases just return `None` as we do not want to
            # run validations against an empty value
            else:
                return None

        # Run the validations for this field and return the value once passed

        # Validate the type of the value for this Field
        self._validate_type(value)

        # Call the rest of the validators defined for this Field
        self._run_validators(value)

        return value
