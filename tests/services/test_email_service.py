""" Test the Email Service using the Local Mem Backend """

from protean.impl.email.local_mem import EmailBackend
from protean.services import email
from protean.services.email import EmailMessage
from protean.services.email import get_connection
from protean.services.email import send_mail
from protean.services.email import send_mass_mail


class TestEmailService:
    """This class holds tests for Email Service"""

    @classmethod
    def setup_class(cls):
        """ Setup the test cases of this class"""
        cls.connection = get_connection()

    def test_init(self):
        """Test successful access to the email backend"""
        with EmailBackend() as connection:
            assert connection is not None

    def test_send_mail(self):
        """ Test sending an email message using default backend """
        # Send the email and check the outbox
        send_mail('Test Subject', 'Test Body', ['jane@domain.com'],
                  connection=self.connection)

        assert email.outbox is not None
        assert email.outbox[-1].message() == ("johndoe@domain.com\n"
                                              "['jane@domain.com']\n"
                                              "Test Subject\n"
                                              "Test Body")

    def test_send_mass_mail(self):
        """ Test sending an mass mail messages using default backend """
        # Send the email and check the outbox
        send_mass_mail(
            [('Test Subject 2', 'Test Body 2', 'doe@domain.com',
              ['jane@domain.com']),
             ('Test Subject 3', 'Test Body 3', None, ['jane@domain.com'])],
            connection=self.connection)

        assert email.outbox[-1].message() == ("johndoe@domain.com\n"
                                              "['jane@domain.com']\n"
                                              "Test Subject 3\n"
                                              "Test Body 3")
        assert email.outbox[-2].message() == ("doe@domain.com\n"
                                              "['jane@domain.com']\n"
                                              "Test Subject 2\n"
                                              "Test Body 2")

    def test_message_send(self):
        """ Test sending an email using from the EmailMessage"""
        message = EmailMessage(
            'Test Subject 4', 'Test Body 4', to=['jane@domain.com'])
        message.send()

        assert email.outbox[-1].message() == ("johndoe@domain.com\n"
                                              "['jane@domain.com']\n"
                                              "Test Subject 4\n"
                                              "Test Body 4")
