""" Define the interface for the email service """

from .base import BaseEmailBackend
from .message import EmailMessage
from .utils import get_connection
from .utils import send_mail
from .utils import send_mass_mail

__all__ = ('BaseEmailBackend', 'EmailMessage', 'get_connection', 'send_mail',
           'send_mass_mail')
