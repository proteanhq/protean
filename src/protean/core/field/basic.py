""" Module for defining basic Field types of Entity """

# Standard Library Imports
import datetime

# Protean
from dateutil.parser import parse as date_parser
from protean.core.exceptions import InvalidOperationError
from protean.core.field import validators
from protean.core.field.base import Field


class String(Field):
    """Concrete field implementation for the string type.

    :param max_length: The maximum allowed length for the field.
    :param min_length: The minimum allowed length for the field.

    FIXME Should max_length be optional?
    """

    default_error_messages = {
        "invalid": '{value}" value must be a string.',
    }

    def __init__(self, max_length=255, min_length=None, **kwargs):
        self.min_length = min_length
        self.max_length = max_length
        self.default_validators = [
            validators.MinLengthValidator(self.min_length),
            validators.MaxLengthValidator(self.max_length),
        ]
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """ Convert the value to its string representation"""
        if isinstance(value, str) or value is None:
            return value
        return str(value)


class Text(Field):
    """Concrete field implementation for the text type.
    """

    default_error_messages = {
        "invalid": '{value}" value must be a string.',
    }

    def _cast_to_type(self, value):
        """ Convert the value to its string representation"""
        if isinstance(value, str) or value is None:
            return value
        return str(value)


class Integer(Field):
    """Concrete field implementation for the Integer type.

    :param min_value: The minimum allowed value for the field.
    :param max_value: The maximum allowed value for the field.

    """

    default_error_messages = {
        "invalid": '"{value}" value must be an integer.',
    }

    def __init__(self, min_value=None, max_value=None, **kwargs):
        self.min_value = min_value
        self.max_value = max_value
        self.default_validators = [
            validators.MinValueValidator(self.min_value),
            validators.MaxValueValidator(self.max_value),
        ]
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """ Convert the value to an int and raise error on failures"""
        try:
            if isinstance(value, str):
                if value.strip() == "":
                    return None
            return int(value)
        except (ValueError, TypeError):
            self.fail("invalid", value=value)


class Float(Field):
    """Concrete field implementation for the Floating type.

    :param min_value: The minimum allowed value for the field.
    :param max_value: The maximum allowed value for the field.

    """

    default_error_messages = {
        "invalid": '"{value}" value must be floating point number.',
    }

    def __init__(self, min_value=None, max_value=None, **kwargs):
        self.min_value = min_value
        self.max_value = max_value
        self.default_validators = [
            validators.MinValueValidator(self.min_value),
            validators.MaxValueValidator(self.max_value),
        ]
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """ Convert the value to a float and raise error on failures"""
        try:
            return float(value)
        except (ValueError, TypeError):
            self.fail("invalid", value=value)


class Boolean(Field):
    """Concrete field implementation for the Boolean type.
    """

    default_error_messages = {
        "invalid": '"{value}" value must be either True or False.',
    }

    def _cast_to_type(self, value):
        """ Convert the value to a boolean and raise error on failures"""
        if value in (True, False):
            return bool(value)
        if value in ("t", "True", "1"):
            return True
        if value in ("f", "False", "0"):
            return False
        self.fail("invalid", value=value)


class List(Field):
    """Concrete field implementation for the List type.
    """

    default_error_messages = {
        "invalid": '"{value}" value must be of list type.',
    }

    def _cast_to_type(self, value):
        """ Raise error if the value is not a list """
        if not isinstance(value, list):
            self.fail("invalid", value=value)
        return value


class Set(Field):
    """Concrete field implementation for the Set type.
    """

    default_error_messages = {
        "invalid": '"{value}" value must be of set type.',
    }

    def _cast_to_type(self, value):
        """ Raise error if the value is not a set """
        if not isinstance(value, set):
            self.fail("invalid", value=value)
        return value


class Dict(Field):
    """Concrete field implementation for the Dict type.
    """

    default_error_messages = {
        "invalid": '"{value}" value must be of dict type.',
    }

    def _cast_to_type(self, value):
        """ Raise error if the value is not a dict """
        if not isinstance(value, dict):
            self.fail("invalid", value=value)
        return value


class Auto(Field):
    """ Concrete field implementation for the Database Autogenerated types.
    """

    def __init__(self, *args, **kwargs):
        """Initialize an Auto Field"""
        # Force set required to false
        super().__init__(*args, **kwargs)
        self.required = False

    def __set__(self, instance, value):
        """An Identifier Field once set cannot be reset or changed.
        We override the ``__set__`` method and prevent setting of new value if one was
        already set and is different from the new value
        """
        existing_value = getattr(instance, self.field_name)
        if existing_value is not None and value != existing_value:
            raise InvalidOperationError("Identifiers cannot be changed once set")

        value = self._load(value)
        instance.__dict__[self.field_name] = value

        if hasattr(instance, "state_"):
            # Mark Entity as Dirty
            instance.state_.mark_changed()

    def _cast_to_type(self, value):
        """ Perform no validation for auto fields. Return the value as is"""
        return value


class Identifier(Field):
    """ Concrete field implementation for Identifiers.

    Values can be Integers or Strings.
    """

    def _cast_to_type(self, value):
        """ Perform no validation for identifier fields. Return the value as is"""
        return value


class CustomObject(Field):
    """Concrete field implementation for objects. Values are instances of custom classes"""

    def _cast_to_type(self, value):
        """ Perform no validation for identifier fields. Return the value as is"""
        return value


class Method(Field):
    """Helper field for custom methods associated with serializer fields"""

    def __init__(self, method_name, **kwargs):
        self.method_name = method_name
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """ Perform no validation for identifier fields. Return the value as is"""
        return value


class Nested(Field):
    """Helper field for nested objects associated with serializer fields"""

    def __init__(self, schema_name, many=False, **kwargs):
        self.schema_name = schema_name
        self.many = many
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """ Perform no validation for identifier fields. Return the value as is"""
        return value


class Date(Field):
    """ Concrete field implementation for the Date type.
    """

    default_error_messages = {
        "invalid": '"{value}" has an invalid date format.',
    }

    def _cast_to_type(self, value):
        """ Convert the value to a date and raise error on failures"""
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        try:
            value = date_parser(value)
            return value.date()
        except ValueError:
            self.fail("invalid", value=value)


class DateTime(Field):
    """ Concrete field implementation for the Datetime/Timestamp type.
    """

    def _cast_to_type(self, value):
        """ Convert the value to a datetime and raise error on failures"""
        if isinstance(value, datetime.datetime):
            return value
        if isinstance(value, datetime.date):
            value = datetime.datetime(value.year, value.month, value.day)
            return value
        try:
            value = date_parser(value)
            return value
        except ValueError:
            self.fail("invalid", value=value)
