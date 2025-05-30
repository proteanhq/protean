from __future__ import annotations

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Type

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin

if TYPE_CHECKING:
    from protean.domain import Domain

logger = logging.getLogger(__name__)


class BaseSubscriber(Element, OptionsMixin):
    """Base Subscriber class that should implemented by all Domain Subscribers.

    This is also a marker class that is referenced when subscribers are registered
    with the domain
    """

    element_type = DomainObjects.SUBSCRIBER

    def __new__(cls, *args, **kwargs):
        if cls is BaseSubscriber:
            raise NotSupportedError("BaseSubscriber cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        return [("broker", "default"), ("channel", None)]

    @abstractmethod
    def __call__(self, payload: dict) -> None:
        """Placeholder method for receiving notifications on event"""

    @classmethod
    def handle_error(cls, exc: Exception, message: dict) -> None:
        """Error handler method called when exceptions occur during broker message handling.
        This method can be overridden in subclasses to provide custom error handling
        for exceptions that occur during message processing. It allows subscribers to
        recover from errors, log additional information, or perform cleanup operations.
        When an exception occurs in a subscriber's __call__ method:
        1. The exception is caught in Engine.handle_broker_message
        2. Details are logged with traceback information
        3. This handle_error method is called with the exception and original message
        4. Processing continues with the next message (the engine does not shut down)
        If this method raises an exception itself, that exception is also caught and logged,
        but not propagated further.
        Args:
            exc (Exception): The exception that was raised during message handling
            message (dict): The original message being processed when the exception occurred
        Returns:
            None
        Note:
            - The default implementation does nothing, allowing processing to continue
            - Subclasses can override this method to implement custom error handling strategies
            - This method is called from a try/except block, so exceptions raised here won't crash the engine
        """


def subscriber_factory(element_cls: Type[Element], domain: "Domain", **opts):
    element_cls = derive_element_class(element_cls, BaseSubscriber, **opts)

    if not element_cls.meta_.channel:
        raise IncorrectUsageError(
            f"Subscriber `{element_cls.__name__}` needs to be associated with an Event"
        )

    if not element_cls.meta_.broker:
        raise IncorrectUsageError(
            f"Subscriber `{element_cls.__name__}` needs to be associated with a Broker"
        )

    return element_cls
