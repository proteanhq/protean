"""Module for defining different validators used by Field Types"""

import re
from typing import Any, cast

from protean.exceptions import ValidationError


class MinLengthValidator:
    """Validate the minimum length for the field value"""

    def __init__(self, min_length: int | None) -> None:
        self.min_length = min_length
        self.message = f"value has less than {self.min_length} characters"

    def __call__(self, value: Any) -> None:
        if self.min_length is not None and len(value) < self.min_length:
            raise ValidationError(self.message)


class MaxLengthValidator:
    """Validate the maximum length for the field value"""

    def __init__(self, max_length: int | None) -> None:
        self.max_length = max_length
        self.message = f"value has more than {self.max_length} characters"

    def __call__(self, value: Any) -> None:
        if self.max_length is not None and len(value) > self.max_length:
            raise ValidationError(self.message)


class MinValueValidator:
    """Validate the minimum value for the field"""

    def __init__(self, min_value: Any) -> None:
        self.min_value = min_value
        self.message = f"value is lesser than {self.min_value}"

    def __call__(self, value: Any) -> None:
        if self.min_value is not None and value < self.min_value:
            raise ValidationError(self.message)


class MaxValueValidator:
    """Validate the maximum value for the field"""

    def __init__(self, max_value: Any) -> None:
        self.max_value = max_value
        self.message = f"value is greater than {self.max_value}"

    def __call__(self, value: Any) -> None:
        if self.max_value is not None and value > self.max_value:
            raise ValidationError(self.message)


class RegexValidator:
    """Validate the regex against given value"""

    regex: str | re.Pattern[str] = ""
    message = "invalid value"
    code = "invalid"
    inverse_match = False
    flags = 0

    def __init__(
        self,
        regex: str | re.Pattern[str] | None = None,
        message: str | None = None,
        code: str | None = None,
        inverse_match: bool | None = None,
        flags: int | None = None,
    ) -> None:
        if regex is not None:
            self.regex = regex
        if message is not None:
            self.message = message
        if code is not None:
            self.code = code
        if inverse_match is not None:
            self.inverse_match = inverse_match
        if flags is not None:
            self.flags = flags
        if self.flags and not isinstance(self.regex, str):
            raise TypeError(
                "If flags are set, regex must be a regular expression string."
            )

        self.regex = re.compile(self.regex, self.flags)

    def __call__(self, value: Any) -> None:
        """
        Validate that the input contains (or does *not* contain, if
        inverse_match is True) a match for the regular expression.
        """
        # ``__init__`` always reassigns ``self.regex`` to the result of
        # ``re.compile``, so at call time it is a compiled pattern regardless
        # of whether a string or pattern was supplied.
        compiled_regex = cast("re.Pattern[str]", self.regex)
        regex_matches = compiled_regex.search(str(value))
        invalid_input = regex_matches if self.inverse_match else not regex_matches
        if invalid_input:
            raise ValidationError(self.message)
