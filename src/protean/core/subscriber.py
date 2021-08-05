import logging

from abc import abstractmethod
from typing import Any, Optional

from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import BaseContainer

logger = logging.getLogger("protean.domain.subscriber")


class BaseSubscriber(BaseContainer):
    """Base Subscriber class that should implemented by all Domain Subscribers.

    This is also a marker class that is referenced when subscribers are registered
    with the domain
    """

    element_type = DomainObjects.SUBSCRIBER

    META_OPTIONS = [("event", None), ("broker", "default")]

    def __new__(cls, *args, **kwargs):
        if cls is BaseSubscriber:
            raise TypeError("BaseSubscriber cannot be instantiated")
        return super().__new__(cls)

    @abstractmethod
    def __call__(self, event: BaseEvent) -> Optional[Any]:
        """Placeholder method for receiving notifications on event"""
        raise NotImplementedError


def subscriber_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseSubscriber, **kwargs)

    if not element_cls.meta_.event:
        raise IncorrectUsageError(
            f"Subscriber `{element_cls.__name__}` needs to be associated with an Event"
        )

    if not element_cls.meta_.broker:
        raise IncorrectUsageError(
            f"Subscriber `{element_cls.__name__}` needs to be associated with a Broker"
        )

    return element_cls
