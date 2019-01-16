"""Module to test Protean Logger"""
import logging
from io import StringIO

from protean.utils.log import configure_logging


def test_protean_logger():
    """ Test the default logger of protean """

    # Override the logging configuration to stream to String IO
    configure_logging()
    logger = logging.getLogger('protean')
    old_stream = logger.handlers[0].stream
    logger_output = StringIO()
    logger.handlers[0].stream = logger_output

    # Make sure that messages are getting logged
    logger.info("Hey, this is an info message.")
    assert logger_output.getvalue().endswith('Hey, this is an info message.\n')

    # Reset to the old logger configuration
    logger.handlers[0].stream = old_stream
