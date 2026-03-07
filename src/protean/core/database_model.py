from abc import abstractmethod

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils import DomainObjects, derive_element_class
from protean.utils.container import Element, OptionsMixin
from protean.utils.reflection import attributes, declared_fields
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

    Subclasses must implement ``from_entity()`` for converting domain objects
    to database records. A default ``to_entity()`` is provided that handles
    the common pattern of iterating attributes with ``referenced_as``
    remapping; override it only when storage-specific logic is needed
    (e.g. Elasticsearch's ``meta.id`` extraction).

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
    def _get_value(cls, item: Any, key: str) -> Any:
        """Extract a single value from a storage record by key.

        Override in adapter subclasses for storage-specific access patterns.
        The default uses ``getattr()``, which works for object-based records
        (e.g. SQLAlchemy ORM instances).
        """
        return getattr(item, key)

    @classmethod
    def to_entity(cls, item: Any) -> "BaseEntity":
        """Convert a database record back into a domain entity/aggregate.

        Iterates entity attributes, applies ``referenced_as`` remapping,
        and reconstructs the domain object.  Adapters with storage-specific
        reconstruction needs (e.g. Elasticsearch ``meta.id`` extraction)
        should override this method entirely.
        """
        item_dict: dict[str, Any] = {}
        for attr_name, attr_obj in attributes(cls.meta_.part_of).items():
            if attr_obj.referenced_as:
                item_dict[attr_obj.field_name] = cls._get_value(
                    item, attr_obj.referenced_as
                )
            else:
                item_dict[attr_name] = cls._get_value(item, attr_name)
        return cls.meta_.part_of(**item_dict)


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
            # Use None default: shadow fields for a None ValueObject are
            # removed from __dict__ by _set_embedded_values, and they are
            # not Pydantic model fields, so bare getattr would raise
            # AttributeError via Pydantic's __getattr__.
            value = getattr(entity, attr_obj.field_name, None)
            key = attr_obj.referenced_as
        else:
            value = getattr(entity, attr_obj.attribute_name, None)
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

    # Validate that model fields exist in the associated aggregate/entity
    part_of_cls = element_cls.meta_.part_of
    entity_field_names = set(declared_fields(part_of_cls).keys())

    _SKIP = {"Meta", "meta_", "element_type"}
    _DESCRIPTOR_TYPES = (classmethod, staticmethod, property)
    model_field_names = {
        name
        for name, value in vars(element_cls).items()
        if not name.startswith("_")
        and name not in _SKIP
        and not callable(value)
        and not isinstance(value, _DESCRIPTOR_TYPES)
    }

    extra = model_field_names - entity_field_names
    if extra:
        raise IncorrectUsageError(
            f"Database Model `{element_cls.__name__}` has field(s) "
            f"{extra} not declared in `{part_of_cls.__name__}`"
        )

    return element_cls
