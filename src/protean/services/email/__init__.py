""" Define the interface for the email service """
from .utils import get_connection, send_mail, send_mass_mail
from .message import EmailMessage
from .base import BaseEmailBackend


__all__ = ('BaseEmailBackend', 'EmailMessage', 'get_connection', 'send_mail',
           'send_mass_mail')
