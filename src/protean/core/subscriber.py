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
