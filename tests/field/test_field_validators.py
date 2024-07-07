"""Test cases for validators"""

import re

import pytest

from protean.exceptions import ValidationError
from protean.fields.validators import (
    MaxLengthValidator,
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    RegexValidator,
)

TEST_DATA = [
    # (validator, value, expected),
    (MinLengthValidator(5), "abcde", None),
    (MinLengthValidator(5), "abcdef", None),
    (MinLengthValidator(5), "abcd", ValidationError),
    (MinLengthValidator(0), "", None),  # Minimum length of 0 with empty string
    (
        MinLengthValidator(1),
        "",
        ValidationError,
    ),  # Minimum length of 1 with empty string
    (MaxLengthValidator(10), "abcde", None),
    (MaxLengthValidator(10), "abcdefghij", None),
    (MaxLengthValidator(10), "abcdefghijkl", ValidationError),
    (MaxLengthValidator(0), "", None),  # Maximum length of 0 with empty string
    (MaxLengthValidator(1), "a", None),  # Maximum length of 1 with single character
    (MaxLengthValidator(1), "ab", ValidationError),  # Exceeding maximum length
    (MinValueValidator(100), 100, None),
    (MinValueValidator(100), 101, None),
    (MinValueValidator(100), 99, ValidationError),
    (MinValueValidator(0), -1, ValidationError),
    (MaxValueValidator(100), 100, None),
    (MaxValueValidator(100), 101, ValidationError),
    (MaxValueValidator(100), 99, None),
    (MinValueValidator(-10), -10, None),  # Minimum value with negative number
    (MaxValueValidator(0), 0, None),  # Maximum value with zero
    (
        MaxValueValidator(0),
        1,
        ValidationError,
    ),  # Exceeding maximum value with positive number
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
    (RegexValidator("[a-z]+"), "abc", None),  # Matching regex with lowercase letters
    (
        RegexValidator("[a-z]+"),
        "ABC",
        ValidationError,
    ),  # Not matching regex with uppercase letters
    (
        RegexValidator("[a-z]+", flags=re.IGNORECASE),
        "ABC",
        None,
    ),  # Matching regex with ignore case flag
    (
        RegexValidator("[a-z]+", inverse_match=True),
        "123",
        None,
    ),  # Inverse match with non-matching string
    (
        RegexValidator("[a-z]+", inverse_match=True),
        "abc",
        ValidationError,
    ),  # Inverse match with matching string
    (RegexValidator(r"\d+"), "123abc", None),  # Regex with digits in a mixed string
    (
        RegexValidator(r"\d+", inverse_match=True),
        "123abc",
        ValidationError,
    ),  # Inverse match with digits in a mixed string
    (RegexValidator("[0-9]+", message="Digits only!"), "abcd", ValidationError),
    (RegexValidator("[0-9]+", message="Digits only!"), "abcd", ValidationError),
    (
        RegexValidator("[0-9]+", message="Digits only!", code="invalid_digits"),
        "abcd",
        ValidationError,
    ),
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

    def test_regex_type_error_exception(self):
        with pytest.raises(TypeError) as exc:
            # Test case for TypeError when flags are set and regex is not a string
            RegexValidator(re.compile("[0-9]+"), flags=re.IGNORECASE)

        assert (
            exc.value.args[0]
            == "If flags are set, regex must be a regular expression string."
        )
