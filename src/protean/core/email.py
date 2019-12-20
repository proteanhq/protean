from abc import abstractmethod

from protean.domain import DomainObjects
from protean.globals import current_domain
from protean.utils import convert_str_values_to_list


class BaseEmailProvider:
    """
    Base class for email backend implementations.

    Concrete implementations must overwrite `send_messages()`.
    ```
    """
    def __init__(self, fail_silently=False, **kwargs):
        self.fail_silently = fail_silently

    @abstractmethod
    def send_email(self, email_messages):
        """
        Send one or more EmailMessage objects and return the number of email
        messages sent.
        """
        raise NotImplementedError(
            'Concrete implementations of BaseEmailBackend '
            'must override send_messages() method')


class _EmailMetaclass(type):
    """
    This base metaclass processes the class declaration and constructs a meta object that can
    be used to introspect the Email class later. Specifically, it sets up a `meta_` attribute on
    the Email to an instance of Meta, either the default of one that is defined in the
    Email class.

    `meta_` is setup with these attributes:
        * `provider`: The email provider that this email message is associated with
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize Email MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of Email
        # (excluding Email class itself).
        parents = [b for b in bases if isinstance(b, _EmailMetaclass)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Remove `abstract` in base classes if defined
        for base in bases:
            if hasattr(base, 'Meta') and hasattr(base.Meta, 'abstract'):
                delattr(base.Meta, 'abstract')

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop('Meta', None)
        meta = attr_meta or getattr(new_class, 'Meta', None)
        setattr(new_class, 'meta_', EmailMeta(name, meta))

        return new_class


class EmailMeta:
    """ Metadata info for the Email.

    Options:
    - ``provider``: The Email provider that this message is associated with
    """

    def __init__(self, entity_name, meta):
        self.provider = getattr(meta, 'provider', None)


class BaseEmail(metaclass=_EmailMetaclass):
    """Base Email class that should implemented by all Domain Email Messages.

    This is also a marker class that is referenced when emails are registered
    with the domain.
    """

    element_type = DomainObjects.EMAIL

    def __new__(cls, *args, **kwargs):
        if cls is BaseEmail:
            raise TypeError("BaseEmail cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, subject='', template='', data='',
                 from_email=None, to=None, bcc=None, cc=None,
                 reply_to=None, provider=None, **kwargs):
        """
        Initialize a single email message (which can be sent to multiple
        recipients).
        """
        self.to = convert_str_values_to_list(to)
        self.cc = convert_str_values_to_list(cc)
        self.bcc = convert_str_values_to_list(bcc)

        self.from_email = from_email or current_domain.config['EMAIL_PROVIDERS']['DEFAULT_FROM_EMAIL']
        self.reply_to = convert_str_values_to_list(reply_to) if reply_to else self.from_email

        self.subject = subject
        self.template = template
        self.data = data
        self.kwargs = kwargs
        self.provider = provider

    @property
    def mime_message(self):
        """ Convert the message to a mime compliant email string """
        return '\n'.join(
            [self.from_email, str(self.to), self.subject[:25], self.body[:25]])

    def __repr__(self):
        """ Convert the message to a mime compliant email string """
        return '\n'.join(
            [self.from_email, str(self.to), self.subject[:25], self.body[:25]])

    @property
    def recipients(self):
        """
        Return a list of all recipients of the email (includes direct
        addressees as well as Cc and Bcc entries).
        """
        return [email for email in (self.to + self.cc + self.bcc) if email]
