"""
Email Integration Suite
"""
import sendgrid
from sendgrid.helpers.mail import Email, Mail, Substitution

from protean.conf import active_config
from protean.core.transport import (InvalidRequestObject, ValidRequestObject)


class EmailHelper:
    """ This class is responsible for sending email"""

    @classmethod
    def send_email(cls, payload, template_id):
        """Method for sending email"""
        send_email_use_case = SendEmailUseCase()
        request_object = SendEmailRequestObject.from_dict({
            'payload': payload,
            'template_id': template_id
        })
        send_email_use_case.send(request_object)


class SendEmailRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for Sending Email
    """

    def __init__(self, payload, template_id):
        """Initialize Request Object with form data"""
        self.payload = payload
        self.template_id = template_id

    @classmethod
    def from_dict(cls, adict):

        invalid_req = InvalidRequestObject()
        data = adict['payload']

        if 'email' not in data:
            invalid_req.add_error('email', 'is mandatory')
        if 'subject' not in data:
            invalid_req.add_error('subject', 'is mandatory')

        if 'template_id' not in adict:
            invalid_req.add_error('template_id', 'is mandatory')

        if invalid_req.has_errors():
            return invalid_req

        return SendEmailRequestObject(data, adict['template_id'])


class SendEmailUseCase:
    """
    This class implements the usecase for sending email
    """

    def send(self, request_object):
        """Send an email"""
        payload = request_object.payload

        sg = sendgrid.SendGridAPIClient(getattr(active_config, 'SENDGRID_API_KEY', None))
        from_email = Email(getattr(active_config, 'SENDGRID_FROM', None))
        to_email = Email(payload.pop('email'))

        assert sg is not None

        mail = Mail(from_email, payload['subject'], to_email)

        for key in payload.keys():
            mail.personalizations[0].add_substitution(
                Substitution('<%{}%>'.format(key), payload[key]))

        mail.template_id = request_object.template_id

        return sg.client.mail.send.post(request_body=mail.get())
