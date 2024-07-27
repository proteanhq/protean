from abc import abstractmethod

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin


class BaseModel(Element, OptionsMixin):
    """This is a Model representing a data schema in the persistence store. A concrete implementation of this
    model has to be provided by each persistence store plugin.
    """

    element_type = DomainObjects.MODEL

    def __new__(cls, *args, **kwargs):
        if cls is BaseModel:
            raise NotSupportedError("BaseModel cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        return [
            ("database", None),
            ("part_of", None),
            ("schema_name", None),
        ]

    @classmethod
    @abstractmethod
    def from_entity(cls, entity):
        """Initialize Model object from Entity object"""

    @classmethod
    @abstractmethod
    def to_entity(cls, *args, **kwargs):
        """Convert Model Object to Entity Object"""


def model_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseModel, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Model `{element_cls.__name__}` should be associated with an Entity or Aggregate"
        )

    return element_cls
