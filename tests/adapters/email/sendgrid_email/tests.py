import pytest
from mock import patch

from protean.adapters.email.sendgrid import SendgridEmailProvider

from .elements import Person, PersonAdded, WelcomeEmail, WelcomeNewPerson


@pytest.mark.sendgrid
class TestEmailTriggering:
    @patch.object(SendgridEmailProvider, "send_email")
    def test_that_email_is_pushed_via_aggregate_command_method(self, mock, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonAdded, part_of=Person)
        test_domain.register(WelcomeEmail)
        test_domain.register(WelcomeNewPerson, event=PersonAdded)

        Person.add_newcomer(
            {
                "email": "john.doe@gmail.com",
                "first_name": "John",
                "last_name": "Doe",
                "age": 21,
            }
        )
        mock.assert_called_once()

    def test_that_sendgrid_email_method_is_called(self, mocker, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonAdded, part_of=Person)
        test_domain.register(WelcomeEmail)
        test_domain.register(WelcomeNewPerson, event=PersonAdded)

        spy = mocker.spy(SendgridEmailProvider, "send_email")

        Person.add_newcomer(
            {
                "email": "subhash.bhushan@gmail.com",
                "first_name": "John",
                "last_name": "Doe",
                "age": 21,
            }
        )
        assert spy.spy_return is True
