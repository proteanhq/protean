"""Test Text field sanitization behavior through domain objects."""

from protean.core.value_object import BaseValueObject
from protean.fields import Text


def test_sanitization_option_for_text_fields():
    text_field1 = Text()
    assert text_field1.sanitize is True

    text_field1 = Text(sanitize=False)
    assert text_field1.sanitize is False


def test_that_text_values_are_automatically_cleaned():
    class CleanVO(BaseValueObject):
        content = Text()

    vo = CleanVO(content="an <script>evil()</script> example")
    assert vo.content == "an &lt;script&gt;evil()&lt;/script&gt; example"


def test_that_sanitization_can_be_optionally_switched_off():
    class RawVO(BaseValueObject):
        content = Text(sanitize=False)

    vo = RawVO(content="an <script>evil()</script> example")
    assert vo.content == "an <script>evil()</script> example"
