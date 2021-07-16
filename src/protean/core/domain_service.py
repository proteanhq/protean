import logging

from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger("protean.domain.service")


class BaseDomainService:
    """Base DomainService class that all other domain services should inherit from.

    This is a placeholder class for now. Methods that are implemented
    in concreate Domain Service classes are inspired from Domain concepts,
    and typically use more than one aggregate to accomplish a task"""

    element_type = DomainObjects.DOMAIN_SERVICE

    def __new__(cls, *args, **kwargs):
        if cls is BaseDomainService:
            raise TypeError("BaseDomainService cannot be instantiated")
        return object.__new__(cls, *args, **kwargs)


def domain_service_factory(element_cls, **kwargs):
    return derive_element_class(element_cls, BaseDomainService)
