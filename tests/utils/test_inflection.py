"""Tests for the case-conversion helpers in ``protean.utils.inflection``."""

from protean.utils.inflection import camelize, underscore


class TestCamelize:
    def test_converts_to_upper_camel_case_by_default(self):
        assert camelize("device_type") == "DeviceType"

    def test_converts_to_lower_camel_case(self):
        assert camelize("device_type", False) == "deviceType"

    def test_does_not_always_undo_underscore(self):
        assert camelize(underscore("IOError")) == "IoError"
