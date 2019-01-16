"""Module for defining extended Field types of Entity """
from .basic import String


class StringShort(String):
    """ String fields that have a maximum length of 15 """

    def __init__(self, min_length=None, **kwargs):
        super().__init__(max_length=15, min_length=min_length, **kwargs)


class StringMedium(String):
    """ String fields that have a maximum length of 50 """

    def __init__(self, min_length=None, **kwargs):
        super().__init__(max_length=50, min_length=min_length, **kwargs)


class StringLong(String):
    """ String fields that have a maximum length of 255 """

    def __init__(self, min_length=None, **kwargs):
        super().__init__(max_length=255, min_length=min_length, **kwargs)
