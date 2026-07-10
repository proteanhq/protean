"""Deprecation warnings for the email subsystem (epic #1102, removed at v1.0.0).

Every email entry point emits ``RemovedInProtean10Warning``:

- registration (both ``@domain.email`` and ``domain.register(...)``),
- ``domain.send_email`` and ``domain.get_email_provider``,
- a non-default ``email_providers`` config block.

Each positive test also asserts the machinery still works after warning
(register/resolve/send), and a critical negative test proves an untouched
(default) config stays silent so the framework does not warn on every domain.
"""

import warnings

import pytest

from protean import Domain
from protean._deprecation import (
    ProteanDeprecationWarning,
    RemovedInProtean10Warning,
)
from protean.core.email import BaseEmail
from protean.exceptions import InsufficientDataError, InvalidDataError
from protean.utils import fully_qualified_name

# Message the register/send/get/config warnings share must name the removal
# version; the email token appears in every subject.
_MATCH = r"deprecated.*v1\.0\.0"


class WelcomeEmail(BaseEmail):
    SUBJECT = "Welcome!"
    TEMPLATE = "Hi %NAME%, welcome!"

    def __init__(self, to=None, data=None):
        if to is None or data is None:
            raise InsufficientDataError("`to` and `data` fields are mandatory")
        if not isinstance(data, dict):
            raise InvalidDataError({"data": ["should be a dict"]})
        super().__init__(subject=self.SUBJECT, template=self.TEMPLATE, data=data, to=to)


class TestEmailRegistrationDeprecated:
    """The registration funnel warns for both decorator and register() paths."""

    def test_decorator_registration_warns(self, test_domain):
        with pytest.warns(RemovedInProtean10Warning, match=_MATCH):

            @test_domain.email
            class AnnotatedEmail:
                pass

        # ... and the element is still registered and usable.
        assert fully_qualified_name(AnnotatedEmail) in test_domain.registry.emails

    def test_register_call_warns(self, test_domain):
        """Proves the ``_register_element`` funnel covers the non-decorator
        ``domain.register(...)`` path too."""
        with pytest.warns(RemovedInProtean10Warning, match=_MATCH):
            test_domain.register(WelcomeEmail)

        assert fully_qualified_name(WelcomeEmail) in test_domain.registry.emails


class TestEmailOperationsDeprecated:
    """``send_email`` and ``get_email_provider`` warn but still work."""

    def test_send_email_warns_and_dispatches(self, test_domain):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            test_domain.register(WelcomeEmail)
            test_domain.init(traverse=False)

        email = WelcomeEmail(to=["john@example.com"], data={"NAME": "John"})
        with pytest.warns(RemovedInProtean10Warning, match=_MATCH):
            # DummyEmailProvider returns without raising; a clean send proves
            # the deprecated path still delegates to the real implementation.
            test_domain.send_email(email)

    def test_get_email_provider_warns_and_resolves(self, test_domain):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            test_domain.register(WelcomeEmail)
            test_domain.init(traverse=False)

        with pytest.warns(RemovedInProtean10Warning, match=_MATCH):
            provider = test_domain.get_email_provider("default")

        assert provider is not None


@pytest.mark.no_test_domain
class TestEmailConfigDeprecated:
    """A non-default ``email_providers`` block warns; the default stays silent."""

    def test_non_default_email_config_warns(self):
        with pytest.warns(RemovedInProtean10Warning, match=_MATCH):
            domain = Domain(
                name="CustomEmail",
                config={
                    "email_providers": {
                        "default": {
                            "provider": "protean.adapters.DummyEmailProvider",
                            "DEFAULT_FROM_EMAIL": "custom@example.com",
                        }
                    }
                },
            )

        # Config is applied, not merely warned about.
        assert (
            domain.config["email_providers"]["default"]["DEFAULT_FROM_EMAIL"]
            == "custom@example.com"
        )

    def test_default_email_config_is_silent(self):
        """Critical negative path: the default ``email_providers`` block is
        present in every domain via ``_deep_merge``. Constructing a domain
        without overriding it must emit NO email deprecation warning, or the
        framework spams every user on every ``Domain()``.
        """
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            Domain(name="DefaultEmail", config={})

        email_warnings = [
            w
            for w in caught
            if isinstance(w.message, ProteanDeprecationWarning)
            and "email_providers" in str(w.message).lower()
        ]
        assert email_warnings == []
