from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any

from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from typing import TypeVar

logger = logging.getLogger(__name__)


class BaseApplicationService(Element, OptionsMixin):
    """Base class for application services -- stateless orchestration layers that
    coordinate use cases between external callers (API controllers, CLI handlers,
    background jobs) and the domain model.

    Application services load aggregates, invoke domain methods, and persist
    results without containing business logic themselves. They are always
    associated with one aggregate via ``part_of``. Use the ``@use_case``
    decorator on methods for automatic ``UnitOfWork`` wrapping.

    Unlike command handlers, application services are invoked directly (not
    via ``domain.process()``) and always return values synchronously.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``type`` | The aggregate class this service orchestrates. Required. |

    Example::

        @domain.application_service(part_of=Order)
        class OrderService(BaseApplicationService):

            @use_case
            def place_order(self, order_data: dict) -> Order:
                order = Order(**order_data)
                repo = domain.repository_for(Order)
                repo.add(order)
                return order
    """

    element_type = DomainObjects.APPLICATION_SERVICE

    def __new__(cls, *args, **kwargs):
        if cls is BaseApplicationService:
            raise NotSupportedError("BaseApplicationService cannot be instantiated")
        return object.__new__(cls, *args, **kwargs)

    @classmethod
    def _default_options(cls):
        return [("part_of", None)]


_T = TypeVar("_T")


def application_service_factory(
    element_cls: type[_T], domain: Any, **opts: Any
) -> type[_T]:
    element_cls = derive_element_class(element_cls, BaseApplicationService, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Application Service `{element_cls.__name__}` needs to be associated with an aggregate"
        )

    return element_cls


def use_case(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to mark a method as a use case in an Application Service.

    Args:
        func: The method to be decorated.

    Returns:
        The decorated method.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(f"Executing use case: {func.__name__}")

        # Wrap in a Unit of Work context
        with UnitOfWork():
            return func(*args, **kwargs)

    setattr(wrapper, "_use_case", True)  # Mark the method as a use case
    return wrapper
