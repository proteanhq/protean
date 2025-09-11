"""Logging configuration for Protean framework.

This module provides centralized logging configuration following Python best practices
similar to Django, Flask, and FastAPI frameworks.
"""

import logging
import os
import sys


def configure_logging(level=None, format_string=None):
    """Configure logging for Protean framework.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_string: Custom format string for log messages
    """
    # Get level from environment or use default
    if level is None:
        level = os.environ.get("PROTEAN_LOG_LEVEL", "INFO").upper()

    # Convert string level to logging constant
    numeric_level = getattr(logging, level, logging.INFO)

    # Default format similar to popular frameworks
    if format_string is None:
        if numeric_level == logging.DEBUG:
            # More detailed format for debug mode
            format_string = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        else:
            # Simpler format for production
            format_string = "%(asctime)s %(levelname)s: %(message)s"

    # Configure root logger
    logging.basicConfig(
        level=numeric_level,
        format=format_string,
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,  # Replace any existing configuration
    )

    # Set specific loggers to appropriate levels
    # Reduce verbosity of third-party libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("elasticsearch").setLevel(logging.WARNING)
    logging.getLogger("redis").setLevel(logging.WARNING)

    # Protean loggers inherit from root by default
    # But we can set specific levels if needed
    if numeric_level == logging.DEBUG:
        # Enable debug for all Protean modules
        logging.getLogger("protean").setLevel(logging.DEBUG)
    else:
        # Normal operation - INFO for engine, WARNING for others
        logging.getLogger("protean.server.engine").setLevel(logging.INFO)
        logging.getLogger("protean.server.subscription").setLevel(logging.INFO)
        logging.getLogger("protean.server.outbox_processor").setLevel(logging.INFO)
        logging.getLogger("protean.core").setLevel(logging.WARNING)
        logging.getLogger("protean.adapters").setLevel(logging.WARNING)


def get_logger(name):
    """Get a logger instance with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Logger instance
    """
    return logging.getLogger(name)
