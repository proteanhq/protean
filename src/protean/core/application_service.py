import logging

from protean.container import Element, OptionsMixin
from protean.utils import DomainObjects, derive_element_class

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

    class Meta:
        abstract = True

    def __new__(cls, *args, **kwargs):
        if cls is BaseApplicationService:
            raise TypeError("BaseApplicationService cannot be instantiated")
        return object.__new__(cls, *args, **kwargs)

    @classmethod
    def _default_options(cls):
        return []


def application_service_factory(element_cls, **kwargs):
    return derive_element_class(element_cls, BaseApplicationService, **kwargs)
