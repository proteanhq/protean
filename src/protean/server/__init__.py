"""
The server module provides functionality for running Protean as a standalone server.

This includes the engine for processing events and commands using Ray.
"""

from protean.server.engine import Engine

__all__ = ['Engine']
