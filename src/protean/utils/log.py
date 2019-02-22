"""Module defines logging related utilities """

import logging.config

from protean.conf import active_config


def configure_logging():
    """ Function to configure the logging for the Protean App"""
    # Load the logger using the logging config
    logging.config.dictConfig(
        active_config.LOGGING_CONFIG)
