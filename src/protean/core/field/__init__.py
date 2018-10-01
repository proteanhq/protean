"""Module for defining different Field types used in Entities"""

from abc import ABCMeta, abstractmethod
from typing import Union, Iterable, Callable, Any
from protean.core import exceptions
from protean.core.field import validators


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

    def __init__(self, default: Union[Callable, str] = None, required: bool = False,
                 validators: Iterable = (), error_messages: dict = None):
        self.default = default
        self.required = required
        self._validators = validators
        self.value = None

        # Collect default error message from self and parent classes
        messages = {}
        for cls in reversed(self.__class__.__mro__):
            messages.update(getattr(cls, 'default_error_messages', {}))
        messages.update(error_messages or {})
        self.error_messages = messages

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

        raise exceptions.ValidationError(msg)

    @property
    def validators(self):
        """
        Some validators can't be created at field initialization time.
        This method provides a way to handle such default validators.
        """
        return [*self.default_validators, *self._validators]

    @abstractmethod
    def validate_type(self, value: Any):
        """ Abstract method to validate the type of the value passed"""
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

    def validate(self, value: Any):
        """
        Validate value and raise ValidationError if necessary. Subclasses
        can override this to provide validation logic.

        :param value: value of the field to be validated

        """
        # Set the value to default if its empty
        if value in self.empty_values and self.default:
            default = self.default
            self.value = default() if callable(default) else default
            return

        #  Check for required attribute of the field
        if value in self.empty_values and self.required:
            self.fail('required')

        # Check the type of the value
        self.validate_type(value)

        # Call the rest of the validators defined for this Field
        self._run_validators(value)

        self.value = value


class String(Field):
    default_error_messages = {
        'invalid_type': 'Value of this Field must be of str type.',
    }

    def __init__(self, min_length=None, max_length=None, **kwargs):
        self.min_length = min_length
        self.max_length = max_length
        self.default_validators.extend([
            validators.MinLengthValidator(self.min_length),
            validators.MaxLengthValidator(self.max_length)
        ])
        super().__init__(**kwargs)

    def validate_type(self, value: str):
        if type(value) != str:
            self.fail('invalid_type')
        return True
