"""Module for Request related Classes"""
# Standard Library Imports
import datetime
import typing

from abc import ABCMeta, abstractmethod
from dataclasses import field, fields, make_dataclass


class BaseRequestObject(metaclass=ABCMeta):
    """An Abstract Class to define a basic Valid Request Object and its functionality

    Can be initialized from a dictionary.

    Mirroring the REST world, a request object is usually associated with an Entity class, which is
    referenced when necessary for performing lifecycle funtions, like validations, persistence etc.
    """
    is_valid = True

    @classmethod
    @abstractmethod
    def from_dict(cls, entity_cls, adict):
        """
        Initialize a Request object from a dictionary.

        This abstract methods should be implemented by a concrete class. Typical tasks executed
        by the child class would be:
        * validatin of request object data
        * deriving of computed attributes
        * reorganization of data to aid business logic execution
        """
        raise NotImplementedError


class RequestObjectFactory:
    """Factory to construct simple request object structures on the fly"""

    @classmethod  # noqa: C901
    def construct(cls, name: str, declared_fields: typing.List[tuple]):
        """
        Utility method packaged along with the factory to be able to construct Request Object
        classes on the fly.

        Example:

        .. code-block:: python

            UserShowRequestObject = Factory.create_request_object(
                'CreateRequestObject',
                [('identifier', int, {'required': True}),
                ('name', str, {'required': True}),
                ('desc', str, {'default': 'Blah'})])

        And then create a request object like so:

        .. code-block:: python

            request_object = UserShowRequestObject.from_dict(
                {'identifier': 112,
                'name': 'Jane',
                'desc': "Doer is not Doe"})

        The third tuple element is a `dict` of the form: {'required': True, 'default': 'John'}

        * ``required`` is False by default, so ``{required: False, default: 'John'}`` and \
            ``{default: 'John'}`` evaluate to the same field definition
        * ``default`` is a *concrete* value of the correct type
        """
        # FIXME Refactor this method to make it simpler

        @classmethod
        def from_dict(cls, adict):
            """Validate and initialize a Request Object"""
            invalid_req = InvalidRequestObject()

            values = {}
            for item in fields(cls):
                value = None
                if item.metadata and 'required' in item.metadata and item.metadata['required']:
                    if item.name not in adict or adict.get(item.name) is None:
                        invalid_req.add_error(item.name, 'is required')
                    else:
                        value = adict[item.name]
                elif item.name in adict:
                    value = adict[item.name]
                elif item.default:
                    value = item.default

                try:
                    if item.type not in [typing.Any, 'typing.Any'] and value is not None:
                        if item.type in [int, float, str, bool, list, dict, tuple,
                                         datetime.date, datetime.datetime]:
                            value = item.type(value)
                        else:
                            if not (isinstance(value, item.type) or issubclass(value, item.type)):
                                invalid_req.add_error(
                                    item.name,
                                    '{} should be of type {}'.format(item.name, item.type))
                except Exception:
                    invalid_req.add_error(
                        item.name,
                        'Value {} for {} is invalid'.format(value, item.name))

                values[item.name] = value

            # Return errors, if any, instead of a request object
            if invalid_req.has_errors:
                return invalid_req

            # Return the initialized Request Object instance
            return cls(**values)

        formatted_fields = cls._format_fields(declared_fields)
        dc = make_dataclass(name, formatted_fields,
                            bases=(BaseRequestObject, ),
                            namespace={'from_dict': from_dict, 'is_valid': True})

        return dc

    @classmethod
    def _format_fields(cls, declared_fields: typing.List[tuple]):
        """Process declared fields and construct a list of tuples
        that can be fed into dataclass constructor factory.
        """
        formatted_fields = []
        for declared_field in declared_fields:
            field_name = field_type = field_defn = None

            # Case when only (name), or "name", is specified
            if isinstance(declared_field, str) or len(declared_field) == 1:
                field_name = declared_field
                field_type = typing.Any
                field_defn = field(default=None)

            # Case when (name, type) are specified
            elif len(declared_field) == 2:
                field_name = declared_field[0]
                field_type = declared_field[1]
                field_defn = field(default=None)

            # Case when (name, type, field) are specified
            elif len(declared_field) == 3:
                field_name = declared_field[0]
                field_type = declared_field[1]

                # Process the definition and create a `field` object
                # Definition will be of the form `{'required': False, 'default': 'John'}`
                assert isinstance(declared_field[2], dict)
                metadata = default = None
                if 'required' in declared_field[2] and declared_field[2]['required']:
                    metadata = {'required': True}
                if 'default' in declared_field[2]:
                    default = declared_field[2]['default']
                field_defn = field(default=default, metadata=metadata)

            formatted_fields.append((field_name, field_type, field_defn))

        return formatted_fields


class InvalidRequestObject:
    """A utility class to represent an Invalid Request Object

    An object of InvalidRequestObject is created with error information and returned to
    the callee, if data was missing or corrupt in the input provided.
    """
    is_valid = False

    def __init__(self):
        """Initialize a blank Request object with no errors"""
        self.errors = []

    def add_error(self, parameter, message):
        """Utility method to append an error message"""
        self.errors.append({'parameter': parameter, 'message': message})

    @property
    def has_errors(self):
        """Indicates if there are errors"""
        return len(self.errors) > 0
