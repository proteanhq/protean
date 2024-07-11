import inspect
import logging

from protean.container import Element, OptionsMixin
from protean.core.event import BaseEvent
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.mixins import HandlerMixin

logger = logging.getLogger(__name__)


class BaseEventHandler(Element, HandlerMixin, OptionsMixin):
    """Base Event Handler to be inherited by all event handlers"""

    element_type = DomainObjects.EVENT_HANDLER

    def __new__(cls, *args, **kwargs):
        if cls is BaseEventHandler:
            raise NotSupportedError("BaseEventHandler cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        part_of = (
            getattr(cls.meta_, "part_of") if hasattr(cls.meta_, "part_of") else None
        )

        return [
            ("part_of", None),
            ("source_stream", None),
            ("stream_name", part_of.meta_.stream_name if part_of else None),
        ]


def event_handler_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseEventHandler, **opts)

    if not (element_cls.meta_.part_of or element_cls.meta_.stream_name):
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
                # Target could be an event or an event type string
                event_type = (
                    method._target_cls.__type__
                    if issubclass(method._target_cls, BaseEvent)
                    else method._target_cls
                )
                element_cls._handlers[event_type].add(method)

    return element_cls
