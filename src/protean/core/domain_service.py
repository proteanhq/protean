import logging

from protean.container import Element, OptionsMixin
from protean.exceptions import IncorrectUsageError
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
        return [
            ("part_of", None),
        ]


def domain_service_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseDomainService, **kwargs)

    if not element_cls.meta_.part_of or len(element_cls.meta_.part_of) < 2:
        raise IncorrectUsageError(
            {
                "_entity": [
                    f"Domain Service `{element_cls.__name__}` needs to be associated with two or more Aggregates"
                ]
            }
        )

    return element_cls
