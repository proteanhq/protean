# Standard Library Imports
from abc import abstractmethod


class _BrokerMetaclass(type):
    """
    This base metaclass processes the class declaration and constructs a meta object that can
    be used to introspect the Broker class later. Specifically, it sets up a `meta_` attribute on
    the Broker to an instance of Meta, either the default of one that is defined in the
    Broker class.

    `meta_` is setup with these attributes:
        * `aggregate`: The aggregate associated with the repository
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize Broker MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of Broker
        # (excluding Broker class itself).
        parents = [b for b in bases if isinstance(b, _BrokerMetaclass)]
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
        setattr(new_class, 'meta_', BrokerMeta(name, meta))

        return new_class


class BrokerMeta:
    """ Metadata info for the Broker.

    Options:
    - ``aggregate_cls``: The aggregate associated with the repository
    """

    def __init__(self, entity_name, meta):
        self.aggregate_cls = getattr(meta, 'aggregate_cls', None)


class BaseBroker(metaclass=_BrokerMetaclass):
    """This class outlines the base broker functions,
    to be satisifed by all implementing brokers.

    It is also a marker interface for registering broker
    classes with the domain"""

    def __init__(self, name, domain, conn_info):
        self.name = name
        self.domain = domain
        self.conn_info = conn_info

    @abstractmethod
    def get_connection(self):
        """Get the connection object to the broker"""

    @abstractmethod
    def send_message(self, initiator_obj):
        """Placeholder method for brokers to accept incoming events"""

    @abstractmethod
    def register(self, domain_event, subscriber_cls):
        """Placeholder method for subscribers to register with broker"""
