""" Test cases for extended field type implementations"""
# Protean
import pytest

from protean.core.exceptions import ValidationError
from protean.core.field.ext import StringShort, StringLong, StringMedium


class TestStringShortField:
    """ Test the StringShort Field Implementation"""

    def test_init(self):
        """Test successful StringShort Field initialization"""

        name = StringShort()
        assert name is not None

    def test_loading(self):
        """ Test loading the value for the StringShort Field"""
        name = StringShort()

        # Check that it raises validation
        with pytest.raises(ValidationError):
            name._load('D' * 16)

        assert name._load('dummy') == 'dummy'


class TestStringMediumField:
    """ Test the StringMedium Field Implementation"""

    def test_init(self):
        """Test successful StringMedium Field initialization"""

        name = StringMedium()
        assert name is not None

    def test_loading(self):
        """ Test loading the value for the StringMedium Field"""
        name = StringMedium()

        # Check that it raises validation
        with pytest.raises(ValidationError):
            name._load('D' * 51)

        assert name._load('dummy') == 'dummy'


class TestStringLongField:
    """ Test the StringLong Field Implementation"""

    def test_init(self):
        """Test successful StringLong Field initialization"""

        name = StringLong()
        assert name is not None

    def test_loading(self):
        """ Test loading the value for the StringLong Field"""
        name = StringLong()

        # Check that it raises validation
        with pytest.raises(ValidationError):
            name._load('D' * 256)

        assert name._load('dummy') == 'dummy'
