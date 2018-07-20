"""Entity Functionality and Classes"""

from abc import ABCMeta
from decimal import Decimal

import bleach

STRING_LENGTHS = {
    'IDENTIFIER': 20,
    'SHORT': 15,
    'MEDIUM': 50,
    'CUSTOM_IDENTIFIER': 50,
    'LONG': 255
}

TYPE_CODES = {
    'BOOLEAN': bool,
    'STRING': str,
    'IDENTIFIER': str,
    'LIST': list,
    'INTEGER': int,
    'TEXT': str,
    'FLOAT': float,
    'DECIMAL': Decimal,
    'DICT': dict,
    'TIMESTAMP': 'TIMESTAMP',  # Validation Not Implemented
    'GEOPOINT': 'GEOPOINT'  # Validation Not Implemented
}


class BaseEntity(metaclass=ABCMeta):
    """Base Class for Domain Entities"""

    _tenant_independent = False
    _fields = []
    _field_definitions = {}
    _mandatory = []
    _unique = []
    _defaults = {}

    def __init__(self, *template, **kwargs):
        """
        This initialization technique supports keyword arguments
        as well as dictionaries. You can even use a template for
        initial data.
        https://stackoverflow.com/questions/2466191/set-attributes-from-dictionary-in-python
        """
        for dictionary in template:
            for key in dictionary:
                setattr(self, key, dictionary[key])
        for key in kwargs:
            setattr(self, key, kwargs[key])
        self.__set_defaults()
        self.__validate()

    def __setattr__(self, name, value):
        """Verify that field is valid before setting on instance"""
        if name not in self._fields:
            raise ValueError(
                "{} is an Invalid Attribute".format(name))
        else:
            # Validate Value against Field Definition
            self.__validate_field_definitions(name, value)

            # Sanitize Value
            value = self.__sanitize(value)

            super().__setattr__(name, value)

    def __validate(self):
        """Validate if all mandatory fields are specified"""
        if not all(field in dir(self) for field in self._mandatory):
            raise ValueError("Not all mandatory fields have been specified")

    def __validate_field_definitions(self, name, value):
        """
        Checks the dictionary and verifies the length and type
        of entities using parameter field_definitions
        """
        errors = {}
        try:
            datatype = self._field_definitions[name]['type']
            if value is not None:
                if datatype in ['IDENTIFIER', 'STRING'] and \
                        isinstance(value, TYPE_CODES[datatype]):
                    datalength = self._field_definitions[name]['length']
                    if len(value) > STRING_LENGTHS[datalength]:
                        raise ValueError("{} has invalid length".format(name))
                elif datatype in ['BOOLEAN', 'INTEGER', 'LIST',
                                  'DICT', 'TEXT', 'FLOAT', 'DECIMAL']:
                    if not isinstance(value, TYPE_CODES[datatype]):
                        raise ValueError("{} - Invalid Value for field {}".format(value, name))
                elif datatype in ['TIMESTAMP', 'GEOPOINT']:
                    # FIXME Implement Timestamp and Geopoint validations
                    pass
                else:
                    raise TypeError("{} - Expected data type as {}, but saw {}".format(
                        name, datatype, type(value)))

            return errors
        except AttributeError:
            return {}

    def __sanitize(self, value):
        """Sanitize all the strings"""
        result = value
        if isinstance(value, str):
            result = bleach.clean(value)
        elif isinstance(value, dict):
            for key, val in value.items():
                result[key] = self.__sanitize(val)

        return result

    def __set_defaults(self):
        """Set defaults if not set already"""
        for key, value in self._defaults.items():
            if getattr(self, key, None) is None:
                setattr(self, key, value)
