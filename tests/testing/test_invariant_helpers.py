"""Tests for the (deprecated) ``assert_invalid`` / ``assert_valid`` helpers.

These helpers were removed in 0.16.0 without a deprecation cycle and restored
in 0.16.1 as deprecated shims. They now emit ``DeprecationWarning``
and will be removed in v0.18.0.
"""

import pytest

from protean.exceptions import ValidationError
from protean.testing import assert_invalid, assert_valid


def _raise_validation_error():
    raise ValidationError({"_entity": ["Product is out of stock"]})


class TestAssertInvalid:
    def test_catches_validation_error_and_returns_it(self):
        with pytest.warns(DeprecationWarning):
            exc = assert_invalid(_raise_validation_error)
        assert isinstance(exc, ValidationError)

    def test_message_match_passes(self):
        with pytest.warns(DeprecationWarning):
            assert_invalid(_raise_validation_error, message="out of stock")

    def test_message_mismatch_raises_assertion_error(self):
        with pytest.warns(DeprecationWarning), pytest.raises(AssertionError):
            assert_invalid(_raise_validation_error, message="not present")

    def test_no_error_raises_assertion_error(self):
        with pytest.warns(DeprecationWarning), pytest.raises(AssertionError):
            assert_invalid(lambda: None)


class TestAssertValid:
    def test_passes_through_return_value(self):
        with pytest.warns(DeprecationWarning):
            result = assert_valid(lambda: 42)
        assert result == 42

    def test_validation_error_raises_assertion_error(self):
        with pytest.warns(DeprecationWarning), pytest.raises(AssertionError):
            assert_valid(_raise_validation_error)


class TestDeprecationContract:
    """Both helpers must warn with their name and the removal version."""

    def test_assert_invalid_warns_with_removal_version(self):
        with pytest.warns(DeprecationWarning, match=r"assert_invalid.*v0\.18\.0"):
            assert_invalid(_raise_validation_error)

    def test_assert_valid_warns_with_removal_version(self):
        with pytest.warns(DeprecationWarning, match=r"assert_valid.*v0\.18\.0"):
            assert_valid(lambda: None)
