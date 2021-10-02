""" Define the send-grid email provider """
import logging

from python_http_client.exceptions import HTTPError
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, TemplateId

from protean.core.email import BaseEmailProvider

logger = logging.getLogger("protean.email.sendgrid")


class SendgridEmailProvider(BaseEmailProvider):
    """An email provider for sending emails using the Sendgrid Service"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sg_client = SendGridAPIClient(self.conn_info["API_KEY"])

    def send_email(self, message, dynamic_template=False):
        """ Send messages via the sendgrid api"""

        email = Mail(
            from_email=message.from_email or self.conn_info["DEFAULT_FROM_EMAIL"],
            to_emails=message.to,
        )
        email.dynamic_template_data = message.data
        email.template_id = TemplateId(message.template)

        try:
            response = self.sg_client.send(email)

            if response.status_code != 202:
                logger.error(
                    f"Failure: ({response.status_code}) - "
                    f"{response.reason} - {response.body}"
                )

            logger.debug("Email pushed to SendGrid successfully.")
        except HTTPError as e:
            logger.error(f"{e}: {e.to_dict}")
        except Exception as e:
            logger.error(f"Exception: Error while sending email: {e}")

        return True
