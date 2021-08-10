""" Test cases for validators"""
import re

import pytest

from protean.core.field.validators import (
    MaxLengthValidator,
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    RegexValidator,
)
from protean.exceptions import ValidationError

TEST_DATA = [
    # (validator, value, expected),
    (MinLengthValidator(5), "abcde", None),
    (MinLengthValidator(5), "abcdef", None),
    (MinLengthValidator(5), "abcd", ValidationError),
    (MaxLengthValidator(10), "abcde", None),
    (MaxLengthValidator(10), "abcdefghij", None),
    (MaxLengthValidator(10), "abcdefghijkl", ValidationError),
    (MinValueValidator(100), 100, None),
    (MinValueValidator(100), 101, None),
    (MinValueValidator(100), 99, ValidationError),
    (MinValueValidator(0), -1, ValidationError),
    (MaxValueValidator(100), 100, None),
    (MaxValueValidator(100), 101, ValidationError),
    (MaxValueValidator(100), 99, None),
    (RegexValidator(), "", None),
    (RegexValidator(), "x1x2", None),
    (RegexValidator("[0-9]+"), "xxxxxx", ValidationError),
    (RegexValidator("[0-9]+"), "1234", None),
    (RegexValidator(re.compile("[0-9]+")), "1234", None),
    (RegexValidator(".*"), "", None),
    (RegexValidator(re.compile(".*")), "", None),
    (RegexValidator(".*"), "xxxxx", None),
    (RegexValidator("x"), "y", ValidationError),
    (RegexValidator(re.compile("x")), "y", ValidationError),
    (RegexValidator("x", inverse_match=True), "y", None),
    (RegexValidator(re.compile("x"), inverse_match=True), "y", None),
    (RegexValidator("x", inverse_match=True), "x", ValidationError),
    (RegexValidator(re.compile("x"), inverse_match=True), "x", ValidationError),
    (RegexValidator("x", flags=re.IGNORECASE), "y", ValidationError),
    (RegexValidator("a"), "A", ValidationError),
    (RegexValidator("a", flags=re.IGNORECASE), "A", None),
]


class TestValidators:
    def test_validators(self):
        for index, (validator, value, expected) in enumerate(TEST_DATA):
            exception_expected = expected is not None and issubclass(
                expected, Exception
            )

            print(
                "Test No: ",
                index,
                " - Validator: ",
                validator,
                " - value: ",
                value,
                " - expected: ",
                expected,
            )
            if exception_expected:
                with pytest.raises(expected):
                    validator(value)
            else:
                assert validator(value) is None
