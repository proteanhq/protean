import functools
import inspect
import logging

from collections import defaultdict
from typing import Callable

from protean import BaseEvent
from protean.container import Element, OptionsMixin
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects, derive_element_class, fully_qualified_name

logger = logging.getLogger("protean.domain.event_handler")


class BaseEventHandler(Element, OptionsMixin):
    """Base Event Handler to be inherited by all event handlers"""

    element_type = DomainObjects.EVENT_HANDLER

    def __init_subclass__(subclass) -> None:
        # Associate a `_handlers` map with subclasses.
        #   It can be initialized here because the same object
        #   would be made available across all subclasses,
        #   defeating its purpose.
        setattr(subclass, "_handlers", defaultdict(list))

    @classmethod
    def _default_options(cls):
        return [("aggregate_cls", None)]

    def __new__(cls, *args, **kwargs):
        if cls is BaseEventHandler:
            raise TypeError("BaseEventHandler cannot be instantiated")
        return super().__new__(cls)


class handle:
    """Class decorator to mark handler methods in EventHandler classes.
    """

    def __init__(self, event_cls: BaseEvent) -> None:
        self._event_cls = event_cls

    def __call__(self, fn: Callable) -> Callable:
        """Marks the method with a special `_event_cls` attribute to be able to
        construct a map of handlers later.

        Args:
            fn (Callable): Handler method

        Returns:
            Callable: Handler method with `_event_cls` attribute
        """

        @functools.wraps(fn)
        def wrapper(instance, event):
            # Wrap function call within a UoW
            with UnitOfWork():
                fn(instance, event)

        setattr(wrapper, "_event_cls", self._event_cls)
        return wrapper


def event_handler_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseEventHandler, **kwargs)

    # Iterate through methods marked as `@handle` and construct a handler map
    methods = inspect.getmembers(element_cls, predicate=inspect.isroutine)
    for method_name, method in methods:
        if not (
            method_name.startswith("__") and method_name.endswith("__")
        ) and hasattr(method, "_event_cls"):
            element_cls._handlers[fully_qualified_name(method._event_cls)].append(
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
