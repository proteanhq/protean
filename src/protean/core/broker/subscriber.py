# Standard Library Imports
from abc import abstractmethod

# Protean
from protean.domain import DomainObjects


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
            if hasattr(base, 'Meta') and hasattr(base.Meta, 'abstract'):
                delattr(base.Meta, 'abstract')

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop('Meta', None)
        meta = attr_meta or getattr(new_class, 'Meta', None)
        setattr(new_class, 'meta_', SubscriberMeta(name, meta))

        return new_class


class SubscriberMeta:
    """ Metadata info for the Subscriber.

    Options:
    - ``domain_event``: The domain_event that this subscriber is associated with
    """

    def __init__(self, entity_name, meta):
        self.domain_event_cls = getattr(meta, 'domain_event_cls', None)
        self.broker = getattr(meta, 'broker', None)


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
