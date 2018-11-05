""" Utility classes and functions used throughout Protean"""

from abc import ABCMeta

import logging.config

from importlib import import_module

from protean.conf import active_config


class OptionsMeta(ABCMeta):
    """
    Generic metaclass that sets the ``opts`` class attribute, which is
    the Base class's ``class Meta`` options using the ``options_class`` attr .
    """

    def __new__(mcs, name, bases, attrs):
        klass = super().__new__(mcs, name, bases, attrs)

        # Get the Meta class attribute defined for the base class
        meta = getattr(klass, 'Meta', None)
        if meta:

            # Set klass.opts by initializing the `OPTIONS_CLASS` with the meta
            klass.opts = klass.options_class(meta, klass)

        return klass


def configure_logging():
    """ Function to configure the logging for the Protean App"""
    # Load the logger using the logging config
    logging.config.dictConfig(
        active_config.LOGGING_CONFIG)  # pylint: disable=E1101


def perform_import(val):
    """
    If the given setting is a string import notation,
    then perform the necessary import or imports.
    """
    if val is None:
        return None
    elif isinstance(val, str):
        return import_from_string(val)
    elif isinstance(val, (list, tuple)):
        return [import_from_string(item) for item in val]
    return val


def import_from_string(val):
    """
    Attempt to import a class from a string representation.
    """
    try:
        module_path, class_name = val.rsplit('.', 1)
        module = import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        msg = f"Could not import {val}. {e.__class__.__name__}: {e}"
        raise ImportError(msg)
