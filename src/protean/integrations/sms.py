"""SMS client integration"""

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from protean.conf import active_config
from protean.core.transport import (InvalidRequestObject, ValidRequestObject,
                                    ResponseSuccess, ResponseFailure)


class Sms:
    """
    This class encapsulates the methods for Sending Sms
    """

    @classmethod
    def send_sms(cls, payload):
        """Send sms method"""
        send_sms_use_case = SendSmsUseCase()
        request_object = SendSmsRequestObject.from_dict({
            'payload': payload
        })
        send_sms_use_case.send(request_object)


class SendSmsRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for Sending Sms
    """

    def __init__(self, payload=None):
        """Initialize Request Object with form data"""
        self.payload = payload

    @classmethod
    def from_dict(cls, adict):

        invalid_req = InvalidRequestObject()
        data = adict['payload']

        if 'to' not in data:
            invalid_req.add_error('to', 'is mandatory')
        if 'body' not in data:
            invalid_req.add_error('body', 'is mandatory')

        if invalid_req.has_errors():
            return invalid_req

        return SendSmsRequestObject(data)


class SendSmsUseCase:
    """
    This class implements the usecase for sending sms
    """

    def __init__(self, twilio_client=None):
        if twilio_client:
            self.twilio_client = twilio_client
        else:
            self.twilio_client = Client(
                getattr(active_config, 'TWILIO_ACCOUNT_SID', None),
                getattr(active_config, 'TWILIO_AUTH_TOKEN', None)
            )

        assert twilio_client is not None

    def send(self, request_object):
        """Send SMS"""
        payload = request_object.payload

        if self.is_valid_phone_number(payload['to']):
            try:
                self.twilio_client.api.account.messages.create(
                    to=payload['to'],
                    from_=getattr(active_config, 'SENDER_PHONE', None),
                    body=payload['body']
                )
                return ResponseSuccess({"message": "SMS Sent"})

            except TwilioRestException as err:
                if err.code == 21608:
                    return ResponseFailure.build_unprocessable_error("Unverified number")
                else:
                    raise err
        else:
            return ResponseFailure.build_unprocessable_error("Phone number not found")

    def is_valid_phone_number(self, phone):
        """Validate if the phone number is valid"""
        try:
            self.twilio_client.lookups.phone_numbers(phone).fetch(type='carrier')
            return True
        except TwilioRestException as err:
            if err.code == 20404:
                return False
            else:
                raise err
