"""Module defines logging related utilities """

# Standard Library Imports
import logging.config

# Protean
from protean.conf import active_config


def configure_logging():
    """ Function to configure the logging for the Protean App"""
    # Load the logger using the logging config
    logging.config.dictConfig(
        active_config.LOGGING_CONFIG)
