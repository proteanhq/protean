"""Test Text field sanitization behavior through domain objects.

The framework default is ``sanitize=False``: a Text field declared without an
explicit ``sanitize=`` kwarg stores the raw input. See ``test_string.py`` for
the domain-level default and its precedence.
"""

from protean.core.value_object import BaseValueObject
from protean.fields import Text


def test_sanitization_option_for_text_fields():
    # Unset by default (the framework default is False, resolved at validation).
    assert Text().sanitize is None
    assert Text(sanitize=True).sanitize is True
    assert Text(sanitize=False).sanitize is False


def test_that_unset_text_values_are_not_cleaned_by_default():
    class RawVO(BaseValueObject):
        content = Text()

    vo = RawVO(content="an <script>evil()</script> example")
    assert vo.content == "an <script>evil()</script> example"


def test_that_explicit_sanitize_true_cleans():
    class CleanVO(BaseValueObject):
        content = Text(sanitize=True)

    vo = CleanVO(content="an <script>evil()</script> example")
    assert vo.content == "an &lt;script&gt;evil()&lt;/script&gt; example"


def test_that_sanitization_can_be_explicitly_switched_off():
    class RawVO(BaseValueObject):
        content = Text(sanitize=False)

    vo = RawVO(content="an <script>evil()</script> example")
    assert vo.content == "an <script>evil()</script> example"
