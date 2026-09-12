"""Test Text field sanitization behavior through domain objects.

The framework default is ``sanitize=False``: a Text field declared without an
explicit ``sanitize=`` kwarg stores the raw input. ``test_string.py`` carries the
full precedence matrix; the domain-default tests here cover what is specific to
Text, which reaches the sanitization branch through its own ``field_kind``.
"""

import pytest

from protean import Domain
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


@pytest.mark.no_test_domain
class TestDomainLevelSanitizeDefaultForText:
    """``Text`` resolves through ``field_kind == "text"``, a different branch
    from ``String``'s ``"standard"``. Without these, a regression could leave
    Text ignoring ``[field_defaults] sanitize`` while the String tests stayed
    green.

    ``no_test_domain`` keeps the suite's autouse fixture from initializing an
    unrelated domain: these tests build and enter their own.
    """

    def _domain(self, sanitize_default=None):
        config = (
            {"field_defaults": {"sanitize": sanitize_default}}
            if sanitize_default is not None
            else {}
        )
        return Domain(name="TextSanitizeDefaults", config=config)

    def test_domain_default_true_sanitizes_an_unset_text_field(self):
        class RawVO(BaseValueObject):
            content = Text()

        domain = self._domain(sanitize_default=True)
        domain.register(RawVO)
        domain.init(traverse=False)

        with domain.domain_context():
            vo = RawVO(content="an <script>evil()</script> example")
        assert vo.content == "an &lt;script&gt;evil()&lt;/script&gt; example"

    def test_field_kwarg_false_overrides_domain_default_true(self):
        class RawVO(BaseValueObject):
            content = Text(sanitize=False)

        domain = self._domain(sanitize_default=True)
        domain.register(RawVO)
        domain.init(traverse=False)

        with domain.domain_context():
            vo = RawVO(content="an <script>evil()</script> example")
        assert vo.content == "an <script>evil()</script> example"

    def test_domain_default_absent_leaves_an_unset_text_field_raw(self):
        class RawVO(BaseValueObject):
            content = Text()

        domain = self._domain()
        domain.register(RawVO)
        domain.init(traverse=False)

        with domain.domain_context():
            vo = RawVO(content="an <script>evil()</script> example")
        assert vo.content == "an <script>evil()</script> example"
