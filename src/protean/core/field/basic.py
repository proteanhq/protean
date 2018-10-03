"""Module for defining basic Field types used in Entities"""

from protean.core.field.base import Field
from protean.core.field import validators


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
            validators.MinLengthValidator(self.min_length),
            validators.MaxLengthValidator(self.max_length)
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
            validators.MinValueValidator(self.min_value),
            validators.MaxValueValidator(self.max_value)
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
            validators.MinValueValidator(self.min_value),
            validators.MaxValueValidator(self.max_value)
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
