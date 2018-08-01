"""
Custom Protean exception classes
"""


class ImproperlyConfigured(Exception):
    """An important configuration variable is missing"""


class ObjectNotFoundException(Exception):
    """Object was not found, can raise 404"""
