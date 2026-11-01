from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any, ClassVar, Self, TypeVar

from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
)
from protean.utils import DomainObjects, _check_part_of_kind, _derive_element_class
from protean.utils.container import Element, OptionsMixin

logger = logging.getLogger(__name__)


class BaseApplicationService(Element, OptionsMixin):
    """Base class for application services. An application service runs one
    aggregate's use cases for outside callers, such as API endpoints, CLI
    commands and background jobs.

    A use-case method loads aggregates, calls their methods and saves the
    results. Business logic stays in the domain model. Callers call the method
    directly and get its return value. Mark each use-case method with
    ``@use_case`` to run it inside a ``UnitOfWork``. The Application Services
    guide covers usage.

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

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls is BaseApplicationService:
            raise NotSupportedError("BaseApplicationService cannot be instantiated")
        # `object.__new__` takes only the class. Forwarding the caller's
        # arguments raises `TypeError: object.__new__() takes exactly one
        # argument` for any application service that defines `__init__`, and
        # that message names neither the class nor `__init__`.
        return object.__new__(cls)

    _default_options: ClassVar[list[tuple[str, Any]]] = [
        ("part_of", None),
        ("suppress_checks", ()),
    ]


_T = TypeVar("_T", bound=BaseApplicationService)


def application_service_factory(
    element_cls: type[_T], domain: Any, **opts: Any
) -> type[_T]:
    element_cls = _derive_element_class(element_cls, BaseApplicationService, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Application Service `{element_cls.__name__}` needs to be associated with an aggregate"
        )

    _check_part_of_kind(element_cls)

    return element_cls


def use_case(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to mark a method as a use case in an Application Service.

    Args:
        func: The method to be decorated.

    Returns:
        The decorated method.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger.info(f"Executing use case: {func.__name__}")

        # A use case opens a Unit of Work, which needs a domain to open it
        # against. Without an active context the transaction machinery raises
        # `AttributeError: 'NoneType' object has no attribute 'providers'`,
        # which names neither the use case nor the missing context, so check
        # for the context first.
        # Local import: `protean.domain.context` imports back into this module
        # through the element registry. `exceptions.py` and `entity.py` take the
        # same escape hatch for the same reason.
        from protean.domain.context import has_domain_context  # noqa: PLC0415

        if not has_domain_context():
            raise ConfigurationError(
                f"Use case `{func.__qualname__}` needs an active domain "
                "context, because it runs inside a Unit of Work. Wrap the call "
                "in `with domain.domain_context():`, or use the `test_domain` "
                "fixture, which activates one for you."
            )

        # Wrap in a Unit of Work context
        with UnitOfWork():
            return func(*args, **kwargs)

    setattr(wrapper, "_use_case", True)  # Mark the method as a use case
    return wrapper
