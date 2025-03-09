from abc import abstractmethod

from protean.fields import Dict, List, String, Text
from protean.utils import (
    DomainObjects,
    convert_str_values_to_list,
    derive_element_class,
)
from protean.utils.container import BaseContainer, OptionsMixin


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
    def send_email(self, email_message):
        """Send EmailMessage object via registered email provider."""


class BaseEmail(BaseContainer, OptionsMixin):  # FIXME Remove OptionsMixin
    """Base Email class that should implemented by all Domain Email Messages.

    This is also a marker class that is referenced when emails are registered
    with the domain.
    """

    element_type = DomainObjects.EMAIL

    @classmethod
    def _default_options(cls):
        return [("provider", "default")]

    subject = String()
    from_email = String()
    to = List(content_type=String)
    bcc = List(content_type=String)
    cc = List(content_type=String)
    reply_to = String()

    # Supplied content
    text = Text()
    html = Text()

    # JSON data with template
    data = Dict()
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


def email_factory(element_cls, domain, **opts):
    return derive_element_class(element_cls, BaseEmail)
