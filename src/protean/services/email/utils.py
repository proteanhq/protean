""" Email message and email sending related helper functions. """
from protean.conf import active_config
from protean.utils.importlib import perform_import

from .message import EmailMessage


def get_connection(backend=None, fail_silently=False, **kwargs):
    """Load an email backend and return an instance of it.
    If backend is None (default), use settings.EMAIL_BACKEND.
    Both fail_silently and other keyword arguments are used in the
    constructor of the backend.
    """
    klass = perform_import(backend or active_config.EMAIL_BACKEND)
    return klass(fail_silently=fail_silently, **kwargs)


def send_mail(subject, message, recipient_list, from_email=None,
              fail_silently=False, auth_user=None, auth_password=None,
              connection=None, **kwargs):
    """
    Easy wrapper for sending a single message to a recipient list. All members
    of the recipient list will see the other recipients in the 'To' field.

    """
    connection = connection or get_connection(
        username=auth_user,
        password=auth_password,
        fail_silently=fail_silently,
    )
    mail_message = EmailMessage(subject, message, from_email, recipient_list,
                                **kwargs)

    return connection.send_messages([mail_message])


def send_mass_mail(data_tuple, fail_silently=False, auth_user=None,
                   auth_password=None, connection=None):
    """
    Given a data_tuple of (subject, message, from_email, recipient_list), send
    each message to each recipient list. Return the number of emails sent.
    If from_email is None, use the DEFAULT_FROM_EMAIL setting.

    """
    connection = connection or get_connection(
        username=auth_user,
        password=auth_password,
        fail_silently=fail_silently,
    )
    messages = [
        EmailMessage(subject, message, sender, recipient)
        for subject, message, sender, recipient in data_tuple
    ]
    return connection.send_messages(messages)
