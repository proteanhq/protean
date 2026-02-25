from abc import abstractmethod

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from protean.utils.reflection import attributes
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from protean.core.entity import BaseEntity


class BaseDatabaseModel(Element, OptionsMixin):
    """Base class for database models -- persistence-layer representations
    that map between domain aggregates/entities and database-specific schemas.

    Database models are the bridge between the domain model and the storage
    layer. Each persistence adapter (SQLAlchemy, Elasticsearch, etc.) provides
    its own concrete subclass. Protean auto-generates a default database model
    for every aggregate; use ``@domain.model`` only when you need to customize
    the schema mapping (e.g. column names, indexes, JSON serialization).

    Subclasses must implement ``from_entity()`` and ``to_entity()`` for
    bidirectional conversion between domain objects and database records.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``type`` | The aggregate or entity this model maps. Required. |
    | ``database`` | ``str`` | The database provider name (default: ``"default"``). |
    | ``schema_name`` | ``str`` | Override the storage table/collection name. |
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
    def derive_schema_name(cls) -> str:
        """Derive the storage table/collection name.

        Uses ``meta_.schema_name`` if explicitly set, otherwise falls back
        to the schema name of the associated aggregate or entity.

        Returns:
            str: The resolved schema name.
        """
        if hasattr(cls.meta_, "schema_name") and cls.meta_.schema_name:
            return cls.meta_.schema_name
        else:
            return cls.meta_.part_of.meta_.schema_name

    @classmethod
    def _entity_to_dict(cls, entity: Any) -> dict[str, Any]:
        """Extract attribute values from an entity into a plain dict.

        Handles ``referenced_as`` remapping and flattened value-object
        shadow fields.  Subclass ``from_entity()`` can call this and
        post-process as needed.
        """
        return _entity_to_dict(cls, entity)

    @classmethod
    @abstractmethod
    def from_entity(cls, entity: Any) -> Any:
        """Convert a domain entity/aggregate into a database model instance.

        Implementors should extract field values from the domain object and
        map them to the database-specific representation.

        Args:
            entity (BaseEntity): The domain entity or aggregate to convert.

        Returns:
            The database model instance ready for persistence.
        """

    @classmethod
    @abstractmethod
    def to_entity(cls, *args: Any, **kwargs: Any) -> "BaseEntity":
        """Convert a database record back into a domain entity/aggregate.

        Implementors should reconstruct the domain object from the
        database-specific representation.

        Returns:
            BaseEntity: The reconstituted domain entity or aggregate.
        """


def _entity_to_dict(model_cls: type, entity: Any) -> dict[str, Any]:
    """Extract attribute values from an entity into a plain dict.

    Handles ``referenced_as`` remapping and flattened value-object shadow
    fields.  This is the shared implementation used by all adapter-specific
    ``from_entity()`` methods.

    Args:
        model_cls: A database model class with ``meta_.part_of`` pointing
            to the domain entity/aggregate class.
        entity: The domain entity or aggregate instance.

    Returns:
        A dict mapping storage-level attribute names to their values.
    """
    item_dict: dict[str, Any] = {}
    for attr_obj in attributes(model_cls.meta_.part_of).values():
        if attr_obj.referenced_as:
            value = getattr(entity, attr_obj.field_name)
            key = attr_obj.referenced_as
        else:
            value = getattr(entity, attr_obj.attribute_name)
            key = attr_obj.attribute_name
        item_dict[key] = value
    return item_dict


_T = TypeVar("_T")


def database_model_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    element_cls = derive_element_class(element_cls, BaseDatabaseModel, **opts)

    if not element_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Database Model `{element_cls.__name__}` should be associated with an Entity or Aggregate"
        )

    return element_cls
