# Protean
import pytest

from mock import patch
from protean.core.email import BaseEmail
from protean.impl.email.dummy import DummyEmailProvider
from protean.utils import fully_qualified_name

# Local/Relative Imports
from .elements import Person, PersonAdded, WelcomeEmail, WelcomeNewPerson


class TestEmailInitialization:
    def test_that_base_email_class_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            BaseEmail()

    def test_that_email_can_be_instantiated(self):
        email = WelcomeEmail(to='john.doe@gmail.com', data={'foo': 'bar'})
        assert email is not None


class TestEmailRegistration:
    def test_that_email_can_be_registered_with_domain(self, test_domain):
        test_domain.register(WelcomeEmail)

        assert fully_qualified_name(WelcomeEmail) in test_domain.emails

    def test_that_email_can_be_registered_via_annotations(self, test_domain):
        @test_domain.email
        class AnnotatedEmail:
            def special_method(self):
                pass

        assert fully_qualified_name(AnnotatedEmail) in test_domain.emails


class TestEmailTriggering:
    @patch.object(DummyEmailProvider, 'send_email')
    def test_that_email_is_pushed_via_aggregate_command_method(self, mock, test_domain):
        test_domain.register(PersonAdded)
        test_domain.register(WelcomeEmail)
        test_domain.register(WelcomeNewPerson)

        Person.add_newcomer({'email': 'john.doe@gmail.com', 'first_name': 'John', 'last_name': 'Doe', 'age': 21})
        mock.assert_called_once()
