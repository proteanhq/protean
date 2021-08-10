from abc import abstractmethod

from protean.core.field.basic import Dict, List, String
from protean.utils import (
    DomainObjects,
    convert_str_values_to_list,
    derive_element_class,
)
from protean.utils.container import BaseContainer


class BaseEmailProvider:
    """
    Base class for email backend implementations.

    Concrete implementations must overwrite `send_email()`.
    ```
    """

    def __init__(self, name, domain, conn_info, fail_silently=False, **kwargs):
        self.name = name
        self.domain = domain
        self.conn_info = conn_info
        self.fail_silently = fail_silently

    @abstractmethod
    def send_email(self, email_messages):
        """
        Send one or more EmailMessage objects and return the number of email
        messages sent.
        """
        raise NotImplementedError(
            "Concrete implementations of BaseEmailBackend "
            "must override send_email() method"
        )


class BaseEmail(BaseContainer):
    """Base Email class that should implemented by all Domain Email Messages.

    This is also a marker class that is referenced when emails are registered
    with the domain.
    """

    element_type = DomainObjects.EMAIL

    META_OPTIONS = [("provider", "default")]

    def __new__(cls, *args, **kwargs):
        if cls is BaseEmail:
            raise TypeError("BaseEmail cannot be instantiated")
        return super().__new__(cls)

    subject = String()
    data = Dict()
    from_email = String()
    to = List(content_type=String)
    bcc = List(content_type=String)
    cc = List(content_type=String)
    reply_to = String()
    template = String()

    def defaults(self):
        """
        Initialize a single email message (which can be sent to multiple
        recipients).
        """
        self.to = convert_str_values_to_list(self.to)
        self.cc = convert_str_values_to_list(self.cc)
        self.bcc = convert_str_values_to_list(self.bcc)
        self.reply_to = (
            convert_str_values_to_list(self.reply_to)
            if self.reply_to
            else self.from_email
        )

    @property
    def recipients(self):
        """
        Return a list of all recipients of the email (includes direct
        addressees as well as Cc and Bcc entries).
        """
        return [email for email in (self.to + self.cc + self.bcc) if email]


def email_factory(element_cls, **kwargs):
    return derive_element_class(element_cls, BaseEmail)
