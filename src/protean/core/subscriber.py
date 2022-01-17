import logging

from abc import abstractmethod
from typing import Any, Optional

from protean.container import Element, OptionsMixin
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger(__name__)


class BaseSubscriber(Element, OptionsMixin):
    """Base Subscriber class that should implemented by all Domain Subscribers.

    This is also a marker class that is referenced when subscribers are registered
    with the domain
    """

    element_type = DomainObjects.SUBSCRIBER

    @classmethod
    def _default_options(cls):
        return [("event", None), ("broker", "default")]

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
            {
                "_entity": [
                    f"Subscriber `{element_cls.__name__}` needs to be associated with an Event"
                ]
            }
        )

    if not element_cls.meta_.broker:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Subscriber `{element_cls.__name__}` needs to be associated with a Broker"
                ]
            }
        )

    return element_cls
