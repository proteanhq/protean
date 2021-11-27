import logging

from abc import abstractmethod
from typing import Any, Optional

from protean import BaseEvent
from protean.container import Element, OptionsMixin
from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger("protean.domain.event_handler")


class BaseEventHandler(Element, OptionsMixin):
    """Base Event Handler to be inherited by all event handlers"""

    element_type = DomainObjects.EVENT_HANDLER

    @classmethod
    def _default_options(cls):
        return [("event", None)]

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

    if not element_cls.meta_.event:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Event Handler `{element_cls.__name__}` needs to be associated with an Event"
                ]
            }
        )

    return element_cls
