"""Module for defining basic Field types of Entity"""

import datetime

from uuid import UUID

import bleach

from dateutil.parser import parse as date_parser

from protean.exceptions import InvalidOperationError, ValidationError
from protean.fields import Field, validators


class String(Field):
    """Concrete field implementation for the string type.

    :param max_length: The maximum allowed length for the field.
    :param min_length: The minimum allowed length for the field.

    FIXME Should max_length be optional?
    """

    default_error_messages = {
        "invalid": '{value}" value must be a string.',
    }

    def __init__(self, max_length=255, min_length=None, sanitize=True, **kwargs):
        self.min_length = min_length
        self.max_length = max_length
        self.sanitize = sanitize
        self.default_validators = [
            validators.MinLengthValidator(self.min_length),
            validators.MaxLengthValidator(self.max_length),
        ]
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """Convert the value to its string representation"""
        if value is None:
            return value

        value = value if isinstance(value, str) else str(value)

        return bleach.clean(value) if self.sanitize else value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return value

    def __repr__(self):
        # Generate repr values specific to this field
        values = self._generic_param_values_for_repr()
        if self.max_length != 255:
            values.append(f"max_length={self.max_length}")
        if self.min_length:
            values.append(f"min_length={self.min_length}")
        if not self.sanitize:
            values.append("sanitize=False")

        return f"{self.__class__.__name__}(" + ", ".join(values) + ")"


class Text(Field):
    """Concrete field implementation for the text type."""

    default_error_messages = {
        "invalid": '{value}" value must be a string.',
    }

    def __init__(self, sanitize=True, **kwargs):
        self.sanitize = sanitize
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """Convert the value to its string representation"""
        if value is None:
            return value

        value = value if isinstance(value, str) else str(value)

        return bleach.clean(value) if self.sanitize else value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return value

    def __repr__(self):
        # Generate repr values specific to this field
        values = self._generic_param_values_for_repr()
        if not self.sanitize:
            values.append("sanitize=False")

        return f"{self.__class__.__name__}(" + ", ".join(values) + ")"


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
        """Convert the value to an int and raise error on failures"""
        try:
            if isinstance(value, str):
                if value.strip() == "":
                    return None
            return int(value)
        except (ValueError, TypeError):
            self.fail("invalid", value=value)

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return value

    def __repr__(self):
        # Generate repr values specific to this field
        values = self._generic_param_values_for_repr()
        if self.max_value:
            values.append(f"max_value={self.max_length}")
        if self.min_value:
            values.append(f"min_value={self.min_value}")

        return f"{self.__class__.__name__}(" + ", ".join(values) + ")"


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
        """Convert the value to a float and raise error on failures"""
        try:
            return float(value)
        except (ValueError, TypeError):
            self.fail("invalid", value=value)

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return value

    def __repr__(self):
        # Generate repr values specific to this field
        values = self._generic_param_values_for_repr()
        if self.max_value:
            values.append(f"max_value={self.max_length}")
        if self.min_value:
            values.append(f"min_value={self.min_value}")

        return f"{self.__class__.__name__}(" + ", ".join(values) + ")"


class Boolean(Field):
    """Concrete field implementation for the Boolean type."""

    default_error_messages = {
        "invalid": '"{value}" value must be either True or False.',
    }

    def _cast_to_type(self, value):
        """Convert the value to a boolean and raise error on failures"""
        if value in (True, False):
            return bool(value)
        if value in ("t", "True", "1"):
            return True
        if value in ("f", "False", "0"):
            return False
        self.fail("invalid", value=value)

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return value


class List(Field):
    """Concrete field implementation for the List type."""

    default_error_messages = {
        "invalid": '"{value}" value must be of list type.',
        "invalid_content": "Invalid value {value}",
    }

    def __init__(self, content_type=String, pickled=False, **kwargs):
        if content_type not in [
            Boolean,
            Date,
            DateTime,
            Float,
            Identifier,
            Integer,
            String,
            Text,
            Dict,
        ]:
            raise ValidationError({"content_type": ["Content type not supported"]})
        self.content_type = content_type
        self.pickled = pickled

        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """Raise errors if the value is not a list, or
        the items in the list are not of the right data type.
        """
        if not isinstance(value, list):
            self.fail("invalid", value=value)

        # Try to cast value into the destination type.
        #   Throw error if the underlying type does not support value.
        new_value = []
        try:
            for item in value:
                new_value.append(self.content_type()._load(item))
        except ValidationError:
            self.fail("invalid_content", value=value)

        if new_value != value:
            self.fail("invalid_content", value=value)

        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        # FIXME Convert value of objects that the list holds?
        return value


class Dict(Field):
    """Concrete field implementation for the Dict type."""

    default_error_messages = {
        "invalid": '"{value}" value must be of dict type.',
    }

    def __init__(self, pickled=False, **kwargs):
        self.pickled = pickled

        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """Raise error if the value is not a dict"""

        # Lists are allowed in JSON because Postgres supports them.
        #   All other databases treat these columns as BLOB/Pickled Type.
        if not isinstance(value, (dict, list)):
            self.fail("invalid", value=value)
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        # FIXME Convert value of objects that the dict holds?
        return value


class Auto(Field):
    """Concrete field implementation for the Database Autogenerated types."""

    def __init__(self, increment=False, **kwargs):
        """Initialize an Auto Field

        Values of Auto-fields are generated automatically and cannot be set explicitly.
        They cannot be marked as `required` for this reason - Protean does not accept
        values supplied for Auto fields.
        """
        self.increment = increment

        super().__init__(**kwargs)

        # Force set required to false
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
        """Perform no validation for auto fields. Return the value as is"""
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        if not value:
            return None

        return value if isinstance(value, int) else str(value)

    def __repr__(self):
        # Generate repr values specific to this field
        values = self._generic_param_values_for_repr()
        if self.increment:
            values.append("increment=True")

        return f"{self.__class__.__name__}(" + ", ".join(values) + ")"


class Identifier(Field):
    """Concrete field implementation for Identifiers.

    An identity field is immutable and cannot be changed once set.

    Values can be UUIDs, Integers or Strings.
    """

    def _cast_to_type(self, value):
        """Verify that value is either a UUID, a String or an Integer"""
        # A Boolean value is tested for specifically because `isinstance(value, int)` is `True` for Boolean values
        if not (isinstance(value, (UUID, str, int))) or isinstance(value, bool):
            self.fail("invalid", value=value)
        return value

    def __set__(self, instance, value):
        """An Identifier Field once set cannot be reset or changed if it is the identity of the object.

        We override the ``__set__`` method and prevent setting of new value if one was
        already set and is different from the new value
        """
        if self.identifier is True:
            existing_value = getattr(instance, self.field_name)
            if existing_value is not None and value != existing_value:
                raise InvalidOperationError("Identifiers cannot be changed once set")

        value = self._load(value)
        instance.__dict__[self.field_name] = value

        if hasattr(instance, "state_"):
            # Mark Entity as Dirty
            instance.state_.mark_changed()

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        if isinstance(value, UUID):
            return str(value)
        return value


class Method(Field):
    """Helper field for custom methods associated with serializer fields"""

    def __init__(self, method_name, **kwargs):
        self.method_name = method_name
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """Perform no validation for identifier fields. Return the value as is"""
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return value


class Nested(Field):
    """Helper field for nested objects associated with serializer fields"""

    def __init__(self, schema_name, many=False, **kwargs):
        self.schema_name = schema_name
        self.many = many
        super().__init__(**kwargs)

    def _cast_to_type(self, value):
        """Perform no validation for identifier fields. Return the value as is"""
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return value


class Date(Field):
    """Concrete field implementation for the Date type."""

    default_error_messages = {
        "invalid": '"{value}" has an invalid date format.',
        "datetime": "Expected a date but got a datetime {value}.",
    }

    def _cast_to_type(self, value):
        """Convert the value to a date and raise error on failures"""
        if isinstance(value, str) and not value:
            return None

        if isinstance(value, datetime.datetime):
            self.fail("datetime", value=value)

        if isinstance(value, datetime.date):
            return value

        try:
            value = date_parser(value)

            if not (
                value.hour == 0
                and value.minute == 0
                and value.second == 0
                and value.microsecond == 0
            ):
                self.fail("datetime", value=value)

            return value.date()
        except ValueError:
            self.fail("invalid", value=value)

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return str(value) if value else None


class DateTime(Field):
    """Concrete field implementation for the Datetime/Timestamp type."""

    def _cast_to_type(self, value):
        """Convert the value to a datetime and raise error on failures"""
        if isinstance(value, str) and not value:
            return None

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

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return str(value) if value else None
