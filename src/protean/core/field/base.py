"""Module for defining base Field class"""

import enum
from abc import ABCMeta
from abc import abstractmethod
from typing import Any
from typing import Iterable

from protean.core import exceptions

from .mixins import FieldDescriptorMixin

MISSING_ERROR_MESSAGE = (
    'ValidationError raised by `{class_name}`, but error key `{key}` does '
    'not exist in the `error_messages` dictionary.'
)


class Field(FieldDescriptorMixin, metaclass=ABCMeta):
    """Abstract field from which other fields should extend.

    :param default: If set, this value will be used during entity loading
    if the field value is missing.
    :param required: if `True`, Raise a :exc:`ValidationError` if the field
    value is `None`.
    :param unique: Indicate if this field needs to be checked for uniqueness.
    :param label: Verbose name for this field
    :param choices: Valid choices for this field, if value is not one of the
    choices a `ValidationError` is raised.
    :param validators: Optional list of validators to be applied for this field.
    :param error_messages: Optional list of validators to be applied for
    this field.
    """

    # Default error messages for various kinds of errors.
    default_error_messages = {
        'invalid': 'Value is not a valid type for this field.',
        'unique': '`{model_name:s}` with this `{field_name:s}` already exists.',
        'required': 'This field is required.',
        'invalid_choice': 'Value `{value!r}` is not a valid choice. '
                          'Must be one of {choices!r}',
    }

    # Default validators for a Field
    default_validators = []

    # These values will trigger the self.required check.
    empty_values = (None, '', [], (), {})

    def __init__(self, identifier: bool = False, default: Any = None,
                 required: bool = False, unique: bool = False,
                 label: str = None, choices: enum.Enum = None,
                 validators: Iterable = (), value=None, error_messages: dict = None):

        # Nothing to be passed into FieldCacheMixin for initialization
        super().__init__(**{})

        self.identifier = identifier
        self.default = default

        # Indicates if field values need to be unique within the repository
        # always True for identifier field
        self.unique = True if self.identifier else unique

        # Indicates if this field is required, always True for identifier field
        self.required = True if self.identifier else required

        # Set the choices for this field
        self.choices = choices
        if self.choices:
            self.choice_dict = {}
            for _, member in self.choices.__members__.items():
                if isinstance(member.value, (tuple, list)):
                    self.choice_dict[member.value[0]] = member.value[1]
                else:
                    self.choice_dict[member.value] = member.value

        self.label = label
        self._validators = validators

        # Value holder
        self._value = value

        # Hold a reference to Entity registering the field
        self._entity_cls = None

        # Collect default error message from self and parent classes
        messages = {}
        for cls in reversed(self.__class__.__mro__):
            messages.update(getattr(cls, 'default_error_messages', {}))
        messages.update(error_messages or {})
        self.error_messages = messages

    def __get__(self, instance, owner):
        if hasattr(instance, '__dict__'):
            return instance.__dict__.get(self.field_name, self.value)
        else:
            return None

    def __set__(self, instance, value):
        value = self._load(value)
        instance.__dict__[self.field_name] = value

        # Mark Entity as Dirty
        instance.state_.mark_changed()

    def __delete__(self, instance):
        instance.__dict__.pop(self.field_name, None)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self._value = value if value else None

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
    def _cast_to_type(self, value: Any):
        """
        Abstract method to validate and convert the value passed to native type.
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

    def _load(self, value: Any):
        """
        Load the value for the field, run validators and return the value.
        Subclasses can override this to provide custom load logic.

        :param value: value of the field

        """

        if value in self.empty_values:
            # If a default has been set for the field return it
            if self.default is not None:
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

        # If choices exist then validate that value is be one of the choices
        if self.choices:
            value_list = value
            if not isinstance(value, (list, tuple)):
                value_list = [value]
            for v in value_list:
                if v not in self.choice_dict:
                    self.fail(
                        'invalid_choice', value=v,
                        choices=list(self.choice_dict))

        # Cast and Validate the value for this Field
        value = self._cast_to_type(value)

        # Call the rest of the validators defined for this Field
        self._run_validators(value)

        return value

    def get_cache_name(self):
        return self.field_name
