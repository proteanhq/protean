from abc import abstractmethod

from protean.exceptions import IncorrectUsageError
from protean.utils import DomainObjects


class ModelMeta:
    """ Metadata info for the Model.

    Options:
    - ``entity_cls``: The Entity that this model is associated with
    """

    def __init__(self, meta=None):
        if meta:
            self.entity_cls = getattr(meta, "entity_cls", None)
            self.schema = getattr(meta, "schema", None)
            self.database = getattr(meta, "database", None)
        else:
            self.entity_cls = None
            self.schema = None
            self.database = None


class BaseModel:
    """This is a Model representing a data schema in the persistence store. A concrete implementation of this
    model has to be provided by each persistence store plugin.
    """

    element_type = DomainObjects.MODEL

    def __new__(cls, *args, **kwargs):
        if cls is BaseModel:
            raise TypeError("BaseModel cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    @abstractmethod
    def from_entity(cls, entity):
        """Initialize Model object from Entity object"""

    @classmethod
    @abstractmethod
    def to_entity(cls, *args, **kwargs):
        """Convert Model Object to Entity Object"""


def model_factory(element_cls, **kwargs):
    element_cls.element_type = DomainObjects.MODEL

    if hasattr(element_cls, "Meta"):
        element_cls.meta_ = ModelMeta(element_cls.Meta)
    else:
        element_cls.meta_ = ModelMeta()

    if not (hasattr(element_cls.meta_, "entity_cls") and element_cls.meta_.entity_cls):
        element_cls.meta_.entity_cls = kwargs.pop("entity_cls", None)

    if not (hasattr(element_cls.meta_, "schema") and element_cls.meta_.schema):
        element_cls.meta_.schema = kwargs.pop("schema", None)

    if not (hasattr(element_cls.meta_, "database") and element_cls.meta_.database):
        element_cls.meta_.database = kwargs.pop("database", None)

    if not element_cls.meta_.entity_cls:
        raise IncorrectUsageError(
            "Models need to be associated with an Entity or Aggregate"
        )

    return element_cls
