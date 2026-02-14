"""Test String field sanitization behavior through domain objects."""

from protean.core.value_object import BaseValueObject
from protean.fields import String


def test_sanitization_option_for_string_fields():
    str_field1 = String()
    assert str_field1.sanitize is True

    str_field1 = String(sanitize=False)
    assert str_field1.sanitize is False


def test_that_string_values_are_automatically_cleaned():
    class CleanVO(BaseValueObject):
        name = String()

    vo = CleanVO(name="an <script>evil()</script> example")
    assert vo.name == "an &lt;script&gt;evil()&lt;/script&gt; example"


def test_that_sanitization_can_be_optionally_switched_off():
    class RawVO(BaseValueObject):
        name = String(sanitize=False)

    vo = RawVO(name="an <script>evil()</script> example")
    assert vo.name == "an <script>evil()</script> example"
