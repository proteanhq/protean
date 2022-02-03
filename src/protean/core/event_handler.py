import inspect
import logging

from protean.container import Element, OptionsMixin
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects, derive_element_class, fully_qualified_name
from protean.utils.mixins import HandlerMixin

logger = logging.getLogger(__name__)


class BaseEventHandler(Element, HandlerMixin, OptionsMixin):
    """Base Event Handler to be inherited by all event handlers"""

    element_type = DomainObjects.EVENT_HANDLER

    class Meta:
        abstract = True

    @classmethod
    def _default_options(cls):
        aggregate_cls = (
            getattr(cls.meta_, "aggregate_cls")
            if hasattr(cls.meta_, "aggregate_cls")
            else None
        )

        return [
            ("aggregate_cls", None),
            ("stream_name", aggregate_cls.meta_.stream_name if aggregate_cls else None),
            ("source_stream", None),
        ]

    def __new__(cls, *args, **kwargs):
        if cls is BaseEventHandler:
            raise TypeError("BaseEventHandler cannot be instantiated")
        return super().__new__(cls)


def event_handler_factory(element_cls, **opts):
    element_cls = derive_element_class(element_cls, BaseEventHandler, **opts)

    if not (element_cls.meta_.aggregate_cls or element_cls.meta_.stream_name):
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Event Handler `{element_cls.__name__}` needs to be associated with an aggregate or a stream"
                ]
            }
        )

    # Iterate through methods marked as `@handle` and construct a handler map
    #
    # Also, if `_target_cls` is an event, associate it with the event handler's
    #   aggregate or stream
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_target_cls"):
            # `_handlers` is a dictionary mapping the event to the handler method.
            if method._target_cls == "$any":
                # This replaces any existing `$any` handler, by design. An Event Handler
                # can have only one `$any` handler method.
                element_cls._handlers["$any"] = {method}
            else:
                element_cls._handlers[fully_qualified_name(method._target_cls)].add(
                    method
                )

            # Associate Event with the handler's stream
            if inspect.isclass(method._target_cls) and issubclass(
                method._target_cls, BaseEvent
            ):
                # Order of preference:
                #   1. Stream name defined in event
                #   2. Stream name defined for the event handler
                #   3. Stream name derived from aggregate
                stream_name = element_cls.meta_.stream_name or (
                    element_cls.meta_.aggregate_cls.meta_.stream_name
                    if element_cls.meta_.aggregate_cls
                    else None
                )
                method._target_cls.meta_.stream_name = (
                    method._target_cls.meta_.stream_name or stream_name
                )

    return element_cls
