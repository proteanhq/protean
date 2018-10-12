""" Utility classes and functions used throughout Protean"""

from abc import ABCMeta

import logging.config

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
    logging.config.dictConfig(active_config.LOGGING_CONFIG)
