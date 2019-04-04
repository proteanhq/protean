"""Generic Utilities for Protean functionality"""


class classproperty(object):

    def __init__(self, fget):
        self.fget = fget

    def __get__(self, owner_self, owner_cls):
        return self.fget(owner_cls)


def fully_qualified_name(cls):
    """Return Fully Qualified name along with module"""
    return '.'.join([cls.__module__, cls.__qualname__])
