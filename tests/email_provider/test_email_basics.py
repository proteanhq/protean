"""Tests for BaseEmail basics.

Validates:
- Direct BaseEmail instantiation
- Subclassing with annotated syntax
- defaults() coercion (string → list)
- recipients property
- to_dict() serialization
- extra="forbid" enforcement
- Class-level constants (unannotated) coexistence
- __container_fields__ bridge
- WelcomeEmail custom __init__ pattern
- Domain registration
"""

from __future__ import annotations

from typing import Any

import pytest

from protean.core.email import BaseEmail
from protean.exceptions import InsufficientDataError, InvalidDataError, ValidationError
from protean.utils import fully_qualified_name
from protean.utils.reflection import _FIELDS


# ---------------------------------------------------------------------------
# Test domain elements
# ---------------------------------------------------------------------------
class NotificationEmail(BaseEmail):
    """A simple email with no custom __init__."""

    pass


class WelcomeEmail(BaseEmail):
    """Email with class-level constants and custom __init__."""

    SUBJECT = "Welcome!"
    TEMPLATE = "Hi %NAME%, welcome!"

    def __init__(self, to: Any = None, data: Any = None) -> None:
        if to is None or data is None:
            raise InsufficientDataError("`to` and `data` fields are mandatory")

        if not isinstance(data, dict):
            raise InvalidDataError({"data": ["should be a dict"]})

        super().__init__(subject=self.SUBJECT, template=self.TEMPLATE, data=data, to=to)


# ---------------------------------------------------------------------------
# Tests: Basic Functionality
# ---------------------------------------------------------------------------
class TestEmailBasics:
    def test_base_email_can_be_instantiated(self):
        email = BaseEmail()
        assert email is not None

    def test_base_email_all_fields_default_to_none_or_empty(self):
        email = BaseEmail()
        # After defaults(), list fields become []
        assert email.to == []
        assert email.cc == []
        assert email.bcc == []
        assert email.subject is None
        assert email.from_email is None
        assert email.text is None
        assert email.html is None
        assert email.data is None
        assert email.template is None

    def test_subclass_instantiation(self):
        email = NotificationEmail(
            subject="Test", to=["a@b.com"], from_email="sender@b.com"
        )
        assert email.subject == "Test"
        assert email.to == ["a@b.com"]
        assert email.from_email == "sender@b.com"

    def test_extra_kwargs_rejected(self):
        with pytest.raises(ValidationError):
            NotificationEmail(subject="Test", unknown_field="oops")


# ---------------------------------------------------------------------------
# Tests: defaults() Coercion
# ---------------------------------------------------------------------------
class TestEmailDefaults:
    def test_string_to_converted_to_list(self):
        email = NotificationEmail(to="single@email.com")
        assert email.to == ["single@email.com"]

    def test_list_to_preserved(self):
        email = NotificationEmail(to=["a@b.com", "c@d.com"])
        assert email.to == ["a@b.com", "c@d.com"]

    def test_none_to_becomes_empty_list(self):
        email = NotificationEmail()
        assert email.to == []

    def test_string_cc_converted_to_list(self):
        email = NotificationEmail(cc="cc@email.com")
        assert email.cc == ["cc@email.com"]

    def test_string_bcc_converted_to_list(self):
        email = NotificationEmail(bcc="bcc@email.com")
        assert email.bcc == ["bcc@email.com"]

    def test_reply_to_defaults_to_from_email(self):
        email = NotificationEmail(from_email="sender@b.com")
        assert email.reply_to == "sender@b.com"

    def test_reply_to_with_explicit_value(self):
        email = NotificationEmail(from_email="sender@b.com", reply_to="reply@b.com")
        assert email.reply_to == ["reply@b.com"]


# ---------------------------------------------------------------------------
# Tests: recipients Property
# ---------------------------------------------------------------------------
class TestEmailRecipients:
    def test_recipients_combines_to_cc_bcc(self):
        email = NotificationEmail(to=["a@b.com"], cc=["c@d.com"], bcc=["e@f.com"])
        assert set(email.recipients) == {"a@b.com", "c@d.com", "e@f.com"}

    def test_recipients_empty_when_no_addresses(self):
        email = NotificationEmail()
        assert email.recipients == []

    def test_recipients_with_only_to(self):
        email = NotificationEmail(to=["a@b.com", "x@y.com"])
        assert email.recipients == ["a@b.com", "x@y.com"]


# ---------------------------------------------------------------------------
# Tests: Serialization
# ---------------------------------------------------------------------------
class TestEmailSerialization:
    def test_to_dict(self):
        email = NotificationEmail(
            subject="Hello", to=["a@b.com"], from_email="sender@b.com"
        )
        d = email.to_dict()
        assert d["subject"] == "Hello"
        assert d["to"] == ["a@b.com"]
        assert d["from_email"] == "sender@b.com"
        # All fields present
        assert "cc" in d
        assert "bcc" in d
        assert "text" in d
        assert "html" in d
        assert "data" in d
        assert "template" in d

    def test_bool_true_when_fields_set(self):
        email = NotificationEmail(subject="Hello")
        assert bool(email) is True

    def test_bool_false_when_empty(self):
        email = BaseEmail()
        assert bool(email) is False

    def test_repr(self):
        email = NotificationEmail(subject="Test")
        r = repr(email)
        assert "NotificationEmail" in r

    def test_equality(self):
        e1 = NotificationEmail(subject="Test", to=["a@b.com"])
        e2 = NotificationEmail(subject="Test", to=["a@b.com"])
        assert e1 == e2

    def test_inequality_different_values(self):
        e1 = NotificationEmail(subject="Test1")
        e2 = NotificationEmail(subject="Test2")
        assert e1 != e2

    def test_inequality_different_types(self):
        email = NotificationEmail(subject="Test")
        assert email != "not an email"


# ---------------------------------------------------------------------------
# Tests: Class-level Constants
# ---------------------------------------------------------------------------
class TestEmailClassConstants:
    def test_unannotated_string_constants_preserved(self):
        assert WelcomeEmail.SUBJECT == "Welcome!"
        assert WelcomeEmail.TEMPLATE == "Hi %NAME%, welcome!"

    def test_constants_not_in_model_fields(self):
        assert "SUBJECT" not in WelcomeEmail.model_fields
        assert "TEMPLATE" not in WelcomeEmail.model_fields


# ---------------------------------------------------------------------------
# Tests: WelcomeEmail Pattern (custom __init__ + super())
# ---------------------------------------------------------------------------
class TestEmailWelcomePattern:
    def test_welcome_email_instantiation(self):
        email = WelcomeEmail(to=["john@example.com"], data={"name": "John"})
        assert email.subject == "Welcome!"
        assert email.template == "Hi %NAME%, welcome!"
        assert email.to == ["john@example.com"]
        assert email.data == {"name": "John"}

    def test_welcome_email_requires_to_and_data(self):
        with pytest.raises(InsufficientDataError):
            WelcomeEmail(to=["john@example.com"])

    def test_welcome_email_requires_dict_data(self):
        with pytest.raises(InvalidDataError):
            WelcomeEmail(to=["john@example.com"], data="not a dict")

    def test_welcome_email_string_to_coerced(self):
        email = WelcomeEmail(to="single@example.com", data={"name": "Jane"})
        assert email.to == ["single@example.com"]


# ---------------------------------------------------------------------------
# Tests: __container_fields__ Bridge
# ---------------------------------------------------------------------------
class TestEmailFieldsBridge:
    def test_container_fields_populated(self):
        cf = getattr(NotificationEmail, _FIELDS, {})
        assert len(cf) > 0
        # All base email fields should be present
        expected = {
            "subject",
            "from_email",
            "to",
            "bcc",
            "cc",
            "reply_to",
            "text",
            "html",
            "data",
            "template",
        }
        assert set(cf.keys()) == expected

    def test_shim_field_name(self):
        cf = getattr(NotificationEmail, _FIELDS, {})
        assert cf["subject"].field_name == "subject"
        assert cf["to"].field_name == "to"


# ---------------------------------------------------------------------------
# Tests: Domain Registration
# ---------------------------------------------------------------------------
class TestEmailRegistration:
    def test_register_email(self, test_domain):
        test_domain.register(NotificationEmail)
        assert fully_qualified_name(NotificationEmail) in test_domain.registry.emails

    def test_register_welcome_email(self, test_domain):
        test_domain.register(WelcomeEmail)
        assert fully_qualified_name(WelcomeEmail) in test_domain.registry.emails
