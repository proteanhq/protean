""" Define the interface for the email service """

# Local/Relative Imports
from .base import BaseEmailBackend
from .message import EmailMessage
from .utils import get_connection, send_mail, send_mass_mail

__all__ = ('BaseEmailBackend', 'EmailMessage', 'get_connection', 'send_mail',
           'send_mass_mail')
