""" Define the send-grid email provider """
import logging

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Email, Mail, Personalization, Content

from protean.conf import active_config
from protean.core.email import BaseEmailProvider

logger = logging.getLogger('protean.email.sendgrid')


class SendgridEmailProvider(BaseEmailProvider):
    """An email provider for sending emails using the Sendgrid Service"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sg_client = SendGridAPIClient(active_config.SENDGRID_API_KEY)

    def send_email(self, messages, dynamic_template=False):
        """ Send messages via the sendgrid api"""

        msg_count = 0
        for message in messages:
            sg_mail = Mail(
                Email(message.from_email), message.subject)

            # Set the to address for the email
            sg_person = Personalization()
            for to_email in message.to:
                sg_person.add_to(Email(to_email))

            sg_person._dynamic_template_data = message.kwargs.get('subs', {})

            sg_mail.add_personalization(sg_person)

            # Set the content of the email
            if message.body:
                sg_mail.add_content(Content('text/html', message.body))

            # If template it provided use that
            sg_mail.template_id = message.kwargs.get('template_id')

            # Send the message using the API
            self.sg_client.client.mail.send.post(request_body=sg_mail.get())
            msg_count += 1

        return msg_count
