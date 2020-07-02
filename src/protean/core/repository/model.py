# Standard Library Imports
from abc import abstractmethod

# Protean
from protean.domain import DomainObjects


class ModelMeta:
    """ Metadata info for the Model.

    Options:
    - ``entity_cls``: The Entity that this model is associated with
    """

    def __init__(self, meta=None):
        if meta:
            self.entity_cls = getattr(meta, "entity_cls", None)
            self.schema = getattr(meta, "schema", None)
        else:
            self.entity_cls = None
            self.schema = None


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
