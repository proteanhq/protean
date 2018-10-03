"""Module for defining different Field types used in Entities"""

from abc import ABCMeta, abstractmethod
from typing import Union, Iterable, Callable, Any

from protean.core import exceptions
from protean.core.field import validators as f_validators


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

    def __init__(self, default: Union[Callable, str] = None,
                 required: bool = False, label: str = None,
                 validators: Iterable = (), error_messages: dict = None):

        self.default = default
        self.required = required
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


class String(Field):
    """Concrete field implementation for the string type.

    :param min_length: The minimum allowed length for the field.
    :param max_length: The maximum allowed length for the field.

    """
    default_error_messages = {
        'invalid_type': '{value}" value must be of str type.',
    }

    def __init__(self, min_length=None, max_length=None, **kwargs):
        self.min_length = min_length
        self.max_length = max_length
        self.default_validators = [
            f_validators.MinLengthValidator(self.min_length),
            f_validators.MaxLengthValidator(self.max_length)
        ]
        super().__init__(**kwargs)

    def _validate_type(self, value: str):
        if not isinstance(value, str):
            self.fail('invalid_type', value=value)


class Integer(Field):
    """Concrete field implementation for the Integer type.

    :param min_value: The minimum allowed value for the field.
    :param max_value: The maximum allowed value for the field.

    """
    default_error_messages = {
        'invalid_type': '"{value}" value must be of int type.',
    }

    def __init__(self, min_value=None, max_value=None, **kwargs):
        self.min_value = min_value
        self.max_value = max_value
        self.default_validators = [
            f_validators.MinValueValidator(self.min_value),
            f_validators.MaxValueValidator(self.max_value)
        ]
        super().__init__(**kwargs)

    def _validate_type(self, value):
        if not isinstance(value, int):
            self.fail('invalid_type', value=value)


class Float(Field):
    """Concrete field implementation for the Floating type.

    :param min_value: The minimum allowed value for the field.
    :param max_value: The maximum allowed value for the field.

    """
    default_error_messages = {
        'invalid_type': '"{value}" value must be of float type.',
    }

    def __init__(self, min_value=None, max_value=None, **kwargs):
        self.min_value = min_value
        self.max_value = max_value
        self.default_validators = [
            f_validators.MinValueValidator(self.min_value),
            f_validators.MaxValueValidator(self.max_value)
        ]
        super().__init__(**kwargs)

    def _validate_type(self, value):
        if not isinstance(value, float):
            self.fail('invalid_type', value=value)


class Boolean(Field):
    """Concrete field implementation for the Boolean type.
    """
    default_error_messages = {
        'invalid_type': '"{value}" value must be of bool type.',
    }

    def _validate_type(self, value):
        if not isinstance(value, bool):
            self.fail('invalid_type', value=value)


class List(Field):
    """Concrete field implementation for the List type.
    """
    default_error_messages = {
        'invalid_type': '"{value}" value must be of list type.',
    }

    def _validate_type(self, value):
        if not isinstance(value, list):
            self.fail('invalid_type', value=value)


class Dict(Field):
    """Concrete field implementation for the Dict type.
    """
    default_error_messages = {
        'invalid_type': '"{value}" value must be of dict type.',
    }

    def _validate_type(self, value):
        if not isinstance(value, dict):
            self.fail('invalid_type', value=value)
