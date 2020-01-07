""" Define the send-grid email provider """
import logging

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Content, Mail, MimeType, TemplateId

from protean.core.email import BaseEmailProvider

logger = logging.getLogger('protean.email.sendgrid')


class SendgridEmailProvider(BaseEmailProvider):
    """An email provider for sending emails using the Sendgrid Service"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sg_client = SendGridAPIClient(self.conn_info['API_KEY'])

    def send_email(self, message, dynamic_template=False):
        """ Send messages via the sendgrid api"""

        email = Mail(
            from_email=message.from_email or self.conn_info['DEFAULT_FROM_EMAIL'],
            to_emails=message.to,
            subject=message.subject)
        email.content = Content(
            MimeType.html,
            '<strong>Test, Test, and Test again</strong>')
        email.dynamic_template_data = message.data
        email.template_id = TemplateId(message.template_id)

        try:
            response = self.sg_client.send(email)
            print(response.status_code)
            print(response.body)
            print(response.headers)
        except Exception as e:
            logger.error(f'Error encountered while sending Email: {e}')

        return True
