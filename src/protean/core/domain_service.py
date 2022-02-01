import logging

from protean.container import Element, OptionsMixin
from protean.utils import DomainObjects, derive_element_class

logger = logging.getLogger(__name__)


class BaseDomainService(Element, OptionsMixin):
    """Base DomainService class that all other domain services should inherit from.

    This is a placeholder class for now. Methods that are implemented
    in concreate Domain Service classes are inspired from Domain concepts,
    and typically use more than one aggregate to accomplish a task"""

    element_type = DomainObjects.DOMAIN_SERVICE

    class Meta:
        abstract = True

    def __new__(cls, *args, **kwargs):
        if cls is BaseDomainService:
            raise TypeError("BaseDomainService cannot be instantiated")
        return object.__new__(cls, *args, **kwargs)

    @classmethod
    def _default_options(cls):
        return []


def domain_service_factory(element_cls, **kwargs):
    return derive_element_class(element_cls, BaseDomainService, **kwargs)
