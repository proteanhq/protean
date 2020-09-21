# Standard Library Imports
import logging

from abc import abstractmethod

# Protean
from protean.core.exceptions import IncorrectUsageError
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger("protean.domain.subscriber")


class _SubscriberMetaclass(type):
    """
    This base metaclass processes the class declaration and constructs a meta object that can
    be used to introspect the Subscriber class later. Specifically, it sets up a `meta_` attribute on
    the Subscriber to an instance of Meta, either the default of one that is defined in the
    Subscriber class.

    `meta_` is setup with these attributes:
        * `domain_event`: The domain_event that this subscriber is associated with
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize Subscriber MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of Subscriber
        # (excluding Subscriber class itself).
        parents = [b for b in bases if isinstance(b, _SubscriberMetaclass)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Remove `abstract` in base classes if defined
        for base in bases:
            if hasattr(base, "Meta") and hasattr(base.Meta, "abstract"):
                delattr(base.Meta, "abstract")

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop("Meta", None)
        meta = attr_meta or getattr(new_class, "Meta", None)
        setattr(new_class, "meta_", SubscriberMeta(name, meta))

        return new_class


class SubscriberMeta:
    """ Metadata info for the Subscriber.

    Options:
    - ``domain_event``: The domain_event that this subscriber is associated with
    """

    def __init__(self, entity_name, meta):
        self.domain_event = getattr(meta, "domain_event", None)
        self.broker = getattr(meta, "broker", None)
        self.aggregate_cls = getattr(meta, "aggregate_cls", None)


class BaseSubscriber(metaclass=_SubscriberMetaclass):
    """Base Subscriber class that should implemented by all Domain Subscribers.

    This is also a marker class that is referenced when subscribers are registered
    with the domain
    """

    element_type = DomainObjects.SUBSCRIBER

    def __new__(cls, *args, **kwargs):
        if cls is BaseSubscriber:
            raise TypeError("BaseSubscriber cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    @abstractmethod
    def notify(cls, domain_event):
        """Placeholder method for receiving notifications on domain event"""
        pass


def subscriber_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseSubscriber)

    element_cls.meta_.domain_event = (
        kwargs.pop("domain_event", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.domain_event)
        or None
    )

    element_cls.meta_.broker = (
        kwargs.pop("broker", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.broker)
        or "default"
    )

    if not element_cls.meta_.domain_event:
        raise IncorrectUsageError(
            f"Subscriber `{element_cls.__name__}` needs to be associated with a Domain Event"
        )

    if not element_cls.meta_.broker:
        raise IncorrectUsageError(
            f"Subscriber `{element_cls.__name__}` needs to be associated with a Broker"
        )

    return element_cls
