# Standard Library Imports
import logging

from abc import abstractmethod

# Protean
from protean.core.exceptions import IncorrectUsageError
from protean.domain import DomainObjects

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
        self.bounded_context = getattr(meta, "bounded_context", None)


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


class SubscriberFactory:
    @classmethod
    def prep_class(cls, element_cls, **kwargs):
        if issubclass(element_cls, BaseSubscriber):
            new_element_cls = element_cls
        else:
            try:
                new_dict = element_cls.__dict__.copy()
                new_dict.pop("__dict__", None)  # Remove __dict__ to prevent recursion

                new_element_cls = type(
                    element_cls.__name__, (BaseSubscriber,), new_dict
                )
            except BaseException as exc:
                logger.debug("Error during Element registration:", repr(exc))
                raise IncorrectUsageError(
                    "Invalid class {element_cls.__name__} for type {element_type.value}"
                    " (Error: {exc})",
                )

        cls._validate_subscriber_class(new_element_cls)

        new_element_cls.meta_.domain_event = (
            kwargs.pop("domain_event", None)
            or (
                hasattr(new_element_cls, "meta_") and new_element_cls.meta_.domain_event
            )
            or None
        )
        new_element_cls.meta_.broker = (
            kwargs.pop("broker", None)
            or (hasattr(new_element_cls, "meta_") and new_element_cls.meta_.broker)
            or "default"
        )
        new_element_cls.meta_.bounded_context = kwargs.pop("bounded_context", None) or (
            hasattr(new_element_cls, "meta_") and new_element_cls.meta_.bounded_context
        )
        new_element_cls.meta_.aggregate_cls = (
            kwargs.pop("aggregate_cls", None)
            or (
                hasattr(new_element_cls, "meta_")
                and new_element_cls.meta_.aggregate_cls
            )
            or None
        )

        if not new_element_cls.meta_.domain_event:
            raise IncorrectUsageError(
                f"Subscriber `{new_element_cls.__name__}` needs to be associated with a Domain Event"
            )

        return new_element_cls

    @classmethod
    def _validate_subscriber_class(self, element_cls):
        if not issubclass(element_cls, BaseSubscriber):
            raise AssertionError(
                f"Element {element_cls.__name__} must be subclass of `BaseSubscriber`"
            )

        return True
