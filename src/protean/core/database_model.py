from abc import abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Self, TypeVar, cast

from protean.core.queryset import Record
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields.resolved import serialize_custom_value
from protean.utils import (
    DomainObjects,
    _check_part_of_kind,
    _coerce_uuid_to_str,
    _derive_element_class,
)
from protean.utils.container import Element, OptionsMixin
from protean.utils.reflection import attributes, declared_fields, id_field

if TYPE_CHECKING:
    from protean.core.entity import BaseEntity


class BaseDatabaseModel(Element, OptionsMixin):
    """Base class for database models, which map an aggregate, entity or
    projection to the schema of one kind of database.

    Protean generates a default database model for every aggregate. Declare
    one with ``@domain.database_model`` only to change the mapping, for
    example the table name or adapter-specific field types. See the custom
    database models guide.

    A subclass must implement ``from_entity()``. The default ``to_entity()``
    maps each attribute back by name, using ``referenced_as`` when it is set.
    Override ``to_entity()`` only when the storage needs special handling.

    **Meta Options**

    | Option | Type | Description |
    |--------|------|-------------|
    | ``part_of`` | ``type`` or ``str`` | The aggregate, entity or projection this model maps. Required. A string names the element and is resolved at ``domain.init()``. |
    | ``database`` | ``str`` | The database type this model applies to (e.g. ``"sqlite"``, ``"elasticsearch"``), not a provider name. Without it, the model is used for any database type that has no model of its own. |
    | ``schema_name`` | ``str`` | Override the storage table/collection name. |
    """

    element_type = DomainObjects.DATABASE_MODEL

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls is BaseDatabaseModel:
            raise NotSupportedError("BaseDatabaseModel cannot be instantiated")
        return super().__new__(cls)

    _default_options: ClassVar[list[tuple[str, Any]]] = [
        ("database", None),
        ("part_of", None),
        ("schema_name", None),
        ("suppress_checks", ()),
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
            return cast(str, cls.meta_.schema_name)
        else:
            return cast(str, cls.meta_.part_of.meta_.schema_name)

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
            referenced_as = attr_obj.referenced_as
            if referenced_as:
                # ``field_name`` is always populated for a registered field
                # (set by ``Field.__set_name__``); the ``or attr_name`` fallback
                # only satisfies the ``str | None`` type and is never taken at
                # runtime for fields returned by ``attributes()``.
                field_name = attr_obj.field_name or attr_name
                item_dict[field_name] = cls._get_value(item, referenced_as)
            else:
                item_dict[attr_name] = cls._get_value(item, attr_name)
        return cast("BaseEntity", cls.meta_.part_of(**item_dict))

    @classmethod
    def to_records(cls, items: list[Any], fields: list[str]) -> list[Record]:
        """Build read-only [`Record`][protean.core.queryset.Record] objects
        from storage records, holding only the selected fields.

        [`QuerySet.only`][protean.core.queryset.QuerySet.only] uses this. It
        builds no domain entities, so no validation or invariant runs.
        Adapters with storage-specific record access override this method.

        Args:
            items: The raw storage records returned by ``_filter``.
            fields: Attribute names to read from each record. Each record is
                keyed by these names.

        Returns:
            One ``Record`` per item, in the order of ``items``.
        """
        attrs = attributes(cls.meta_.part_of)
        entity_name = cls.meta_.part_of.__name__
        # Records are keyed by the attribute name the caller selected (what
        # they passed to ``only()``); the value is read from the storage key,
        # honouring ``referenced_as``. Resolve both once for the batch.
        resolved = [
            (attr_name, attrs[attr_name].referenced_as or attr_name)
            for attr_name in fields
        ]
        # A uuid identity is a string in Python (ADR-0021). This read-optimized
        # path bypasses entity construction (and its identity coercion), so an
        # adapter that returns a native UUID for the id column (e.g. SQLAlchemy's
        # GUID type) would surface one here; coerce the identity field itself.
        id_f = id_field(cls.meta_.part_of)
        id_name = id_f.field_name if id_f is not None else None
        records = []
        for item in items:
            data = {}
            for key, source in resolved:
                value = cls._get_value(item, source)
                if key == id_name:
                    value = _coerce_uuid_to_str(value)
                data[key] = value
            records.append(Record(entity_name, data))
        return records


def _entity_to_dict(
    model_cls: type["BaseDatabaseModel"], entity: Any
) -> dict[str, Any]:
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
        # ``field_name`` / ``attribute_name`` are always populated for a
        # registered field (set by ``Field.__set_name__``). ``attributes()``
        # returns fully-bound fields, so these asserts hold for every field;
        # they fail loudly rather than silently writing a ``""`` key if the
        # invariant is ever violated.
        assert attr_obj.field_name is not None
        assert attr_obj.attribute_name is not None
        field_name = attr_obj.field_name
        attribute_name = attr_obj.attribute_name
        referenced_as = attr_obj.referenced_as
        if referenced_as:
            # Use None default: shadow fields for a None ValueObject are
            # removed from __dict__ by _set_embedded_values, and they are
            # not Pydantic model fields, so bare getattr would raise
            # AttributeError via Pydantic's __getattr__.
            value = getattr(entity, field_name, None)
            key = referenced_as
        else:
            value = getattr(entity, attribute_name, None)
            key = attribute_name

        # A custom field (built by ``Custom``) holds an instance of a type the
        # store knows nothing about: SQLAlchemy maps it to a string column and
        # Elasticsearch indexes it raw, so the driver rejects the object on
        # write. Serialize it here, at the boundary every adapter's
        # ``from_entity`` goes through, so every adapter stores the same plain
        # value. ``to_entity`` hands that value back to the field's parser. This
        # covers a custom field inside an embedded value object too, because its
        # shadow attribute carries the real field.
        item_dict[key] = serialize_custom_value(attr_obj, value)
    return item_dict


def check_database_model_fields(model_cls: type[BaseDatabaseModel]) -> None:
    """Check that every field a database model declares exists on its target.

    ``meta_.part_of`` must already be a class.

    Raises:
        IncorrectUsageError: When the model declares a field that the
            aggregate, entity or projection in ``part_of`` does not.
    """
    part_of_cls = model_cls.meta_.part_of
    entity_field_names = set(declared_fields(part_of_cls).keys())

    _SKIP = {"Meta", "meta_", "element_type"}
    _DESCRIPTOR_TYPES = (classmethod, staticmethod, property)
    model_field_names = {
        name
        for name, value in vars(model_cls).items()
        if not name.startswith("_")
        and name not in _SKIP
        and not callable(value)
        and not isinstance(value, _DESCRIPTOR_TYPES)
    }

    extra = model_field_names - entity_field_names
    if extra:
        raise IncorrectUsageError(
            f"Database Model `{model_cls.__name__}` has field(s) "
            f"{extra} not declared in `{part_of_cls.__name__}`"
        )


_T = TypeVar("_T")


def database_model_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    element_cls = _derive_element_class(element_cls, BaseDatabaseModel, **opts)

    # The derived class is always a ``BaseDatabaseModel`` subclass at runtime;
    # narrow the unbound ``type[_T]`` typevar so the injected class attribute
    # (``meta_``) is visible to both type checkers.
    model_cls = cast("type[BaseDatabaseModel]", element_cls)

    if not model_cls.meta_.part_of:
        raise IncorrectUsageError(
            f"Database Model `{model_cls.__name__}` should be associated with an "
            "Aggregate, an Entity or a Projection"
        )

    _check_part_of_kind(model_cls)

    # A string target is resolved at ``domain.init()``, which runs this
    # check once the target class is known.
    if not isinstance(model_cls.meta_.part_of, str):
        check_database_model_fields(model_cls)

    return element_cls
