from abc import abstractmethod

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin


class BaseDatabaseModel(Element, OptionsMixin):
    """This is a Model representing a data schema in the persistence store. A concrete implementation of this
    model has to be provided by each persistence store plugin.
    """

    element_type = DomainObjects.DATABASE_MODEL

    def __new__(cls, *args, **kwargs):
        if cls is BaseDatabaseModel:
            raise NotSupportedError("BaseDatabaseModel cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls):
        return [
            ("database", None),
            ("part_of", None),
            ("schema_name", None),
        ]

    @classmethod
    def derive_schema_name(cls):
        """Derive schema name from database model class"""
        if hasattr(cls.meta_, "schema_name") and cls.meta_.schema_name:
            return cls.meta_.schema_name
        else:
            return cls.meta_.part_of.meta_.schema_name

    @classmethod
    @abstractmethod
    def from_entity(cls, entity):
        """Initialize DatabaseModel object from Entity object"""

    @classmethod
    @abstractmethod
    def to_entity(cls, *args, **kwargs):
        """Convert Database Model Object to Entity Object"""


def database_model_factory(element_cls, domain, **opts):
    element_cls = derive_element_class(element_cls, BaseDatabaseModel, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Database Model `{element_cls.__name__}` should be associated with an Entity or Aggregate"
        )

    return element_cls
