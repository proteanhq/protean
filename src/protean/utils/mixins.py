import functools

from collections import defaultdict
from typing import Callable, Union

from protean.core.unit_of_work import UnitOfWork


class handle:
    """Class decorator to mark handler methods in EventHandler classes."""

    def __init__(self, target_cls: Union["BaseEvent", "BaseCommand"]) -> None:
        self._target_cls = target_cls

    def __call__(self, fn: Callable) -> Callable:
        """Marks the method with a special `_target_cls` attribute to be able to
        construct a map of handlers later.

        Args:
            fn (Callable): Handler method

        Returns:
            Callable: Handler method with `_target_cls` attribute
        """

        @functools.wraps(fn)
        def wrapper(instance, target_obj):
            # Wrap function call within a UoW
            with UnitOfWork():
                fn(instance, target_obj)

        setattr(wrapper, "_target_cls", self._target_cls)
        return wrapper


class HandlerMixin:
    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        # Associate a `_handlers` map with subclasses.
        #   It needs to be initialized here because if it
        #   were initialized in __init__, the same collection object
        #   would be made available across all subclasses,
        #   defeating its purpose.
        setattr(subclass, "_handlers", defaultdict(list))
