"""Module for defining different validators used by Field Types"""

from protean.core.exceptions import ValidationError


class MinLengthValidator:
    """ Validate the minimum length for the field value"""
    def __init__(self, min_length):
        self.min_length = min_length
        self.error = f'Ensure this value has at least ' \
                     f'{self.min_length} characters.'

    def __call__(self, value):
        if self.min_length and len(value) < self.min_length:
            raise ValidationError(self.error)


class MaxLengthValidator:
    """ Validate the maximum length for the field value"""
    def __init__(self, max_length):
        self.max_length = max_length
        self.error = f'Ensure this value has at most ' \
                     f'{self.max_length} characters.'

    def __call__(self, value):
        if self.max_length and len(value) > self.max_length:
            raise ValidationError(self.error)
