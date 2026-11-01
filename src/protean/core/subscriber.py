import logging
from abc import abstractmethod
from typing import Any, ClassVar, Self, TypeVar

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, _derive_element_class
from protean.utils.container import Element, OptionsMixin

logger = logging.getLogger(__name__)


class BaseSubscriber(Element, OptionsMixin):
    """Base class for subscribers that consume messages from external message
    brokers and act as an anti-corruption layer at the domain boundary.

    Subscribers listen to named broker streams, receive raw ``dict`` payloads
    (not typed domain events), and translate external data into domain
    operations. Implement the ``__call__`` method to process incoming messages.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``broker`` | ``str`` | The broker adapter name to consume from (default: ``"default"``). |
    | ``stream`` | ``str`` | The external stream/topic name to subscribe to. Required. |
    """

    element_type = DomainObjects.SUBSCRIBER

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls is BaseSubscriber:
            raise NotSupportedError("BaseSubscriber cannot be instantiated")
        return super().__new__(cls)

    _default_options: ClassVar[list[tuple[str, Any]]] = [
        ("broker", "default"),
        ("stream", None),
        ("suppress_checks", ()),
    ]

    @abstractmethod
    def __call__(self, payload: dict[str, Any]) -> None:
        """Placeholder method for receiving notifications on event"""

    @classmethod
    def handle_error(cls, exc: Exception, message: dict[str, Any]) -> None:
        """Handle an exception raised while the engine processed a broker message.

        Override it to add custom error handling, such as logging more detail
        or cleaning up. The engine logs the failure, calls this method, and
        then moves on to the next message. The default does nothing. An
        exception raised here is logged and not propagated, so it does not
        stop the engine.

        Args:
            exc: The exception raised by the subscriber's ``__call__``.
            message: The message payload being processed when the exception
                occurred.
        """


_T = TypeVar("_T", bound=OptionsMixin)


def subscriber_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    element_cls = _derive_element_class(element_cls, BaseSubscriber, **opts)

    if not element_cls.meta_.stream:
        raise IncorrectUsageError(
            f"Subscriber `{element_cls.__name__}` needs to be associated with a stream"
        )

    if not element_cls.meta_.broker:
        raise IncorrectUsageError(
            f"Subscriber `{element_cls.__name__}` needs to be associated with a Broker"
        )

    return element_cls
