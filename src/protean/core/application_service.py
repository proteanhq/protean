import functools
import logging

from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin

logger = logging.getLogger(__name__)


class BaseApplicationService(Element, OptionsMixin):
    """Base ApplicationService class that all other Application services should inherit from.

    This class is a placeholder class for now. Application concepts directly influence the
    method names in concrete Application Service classes, so no abstract methods are necessary.
    Each Application Service class is usually associated one-to-one with API calls.

    Application services are responsible for fetching the linked domain, initializing repositories,
    caches, and message brokers, and injecting dependencies into the domain layer. These are automatable
    aspects that can be part of the base class in the future.
    """

    element_type = DomainObjects.APPLICATION_SERVICE

    def __new__(cls, *args, **kwargs):
        if cls is BaseApplicationService:
            raise NotSupportedError("BaseApplicationService cannot be instantiated")
        return object.__new__(cls, *args, **kwargs)

    @classmethod
    def _default_options(cls):
        return [("part_of", None)]


def application_service_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseApplicationService, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Application Service `{element_cls.__name__}` needs to be associated with an aggregate"
        )

    return element_cls


def use_case(func):
    """Decorator to mark a method as a use case in an Application Service.

    Args:
        func (Callable): The method to be decorated.

    Returns:
        Callable: The decorated method.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(f"Executing use case: {func.__name__}")

        # Wrap in a Unit of Work context
        with UnitOfWork():
            return func(*args, **kwargs)

    setattr(wrapper, "_use_case", True)  # Mark the method as a use case
    return wrapper
