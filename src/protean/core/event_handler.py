import inspect
import logging

from protean.container import Element, OptionsMixin
from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects, derive_element_class, fully_qualified_name
from protean.utils.mixins import HandlerMixin

logger = logging.getLogger("protean.domain.event_handler")


class BaseEventHandler(Element, HandlerMixin, OptionsMixin):
    """Base Event Handler to be inherited by all event handlers"""

    element_type = DomainObjects.EVENT_HANDLER

    @classmethod
    def _default_options(cls):
        return [("aggregate_cls", None)]

    def __new__(cls, *args, **kwargs):
        if cls is BaseEventHandler:
            raise TypeError("BaseEventHandler cannot be instantiated")
        return super().__new__(cls)


def event_handler_factory(element_cls, **opts):
    element_cls = derive_element_class(element_cls, BaseEventHandler, **opts)

    # Iterate through methods marked as `@handle` and construct a handler map
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_target_cls"):
            element_cls._handlers[fully_qualified_name(method._target_cls)].append(
                method
            )

    if not element_cls.meta_.aggregate_cls:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Event Handler `{element_cls.__name__}` needs to be associated with an Aggregate"
                ]
            }
        )

    return element_cls
