import logging

from abc import abstractmethod
from typing import Any, Optional

from protean.container import Element, OptionsMixin
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger("protean.domain.event_handler")


class BaseEventHandler(Element, OptionsMixin):
    """Base EventHandler class that should implemented by all Domain Event Handlers.
    """

    element_type = DomainObjects.EVENT_HANDLER

    @classmethod
    def _default_options(cls):
        return [("event", None), ("stream_name", None)]

    def __new__(cls, *args, **kwargs):
        if cls is BaseEventHandler:
            raise TypeError("BaseEventHandler cannot be instantiated")
        return super().__new__(cls)

    @abstractmethod
    def __call__(self, event: BaseEvent) -> Optional[Any]:
        """Placeholder method for receiving notifications on event"""
        raise NotImplementedError


def event_handler_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseEventHandler, **kwargs)

    if not element_cls.meta_.stream_name:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"BaseEventHandler `{element_cls.__name__}` needs to be associated with a stream"
                ]
            }
        )

    if not element_cls.meta_.event:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"BaseEventHandler `{element_cls.__name__}` needs to be associated with an event"
                ]
            }
        )

    return element_cls
