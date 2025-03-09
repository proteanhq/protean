from abc import abstractmethod

from protean import exceptions, utils
from protean.exceptions import ValidationError
from protean.utils.globals import current_domain
from protean.utils.reflection import (
    association_fields,
    has_association_fields,
    id_field,
)

from .base import Field, FieldBase
from .mixins import FieldCacheMixin, FieldDescriptorMixin


class _ReferenceField(Field):
    """
    Represents a reference field that can be used to establish associations between entities.

    Args:
        reference (str): The reference field as an attribute.
        **kwargs: Additional keyword arguments to be passed to the base `Field` class.
    """

    def __init__(self, reference, **kwargs):
        """Accept reference field as an attribute, otherwise is a straightforward field"""
        self.reference = reference
        super().__init__(**kwargs)

    def __set__(self, instance, value):
        """Override `__set__` to update relation field and keep it in sync with the shadow
        attribute's value

        Args:
            instance: The instance of the class.
            value: The value to be set.
        """
        value = self._load(value)

        if value:
            instance.__dict__[self.field_name] = value
        else:
            # Important to handle None assignment, and interpret it to mean resetting values
            self._reset_values(instance)

    def __delete__(self, instance):
        """Nullify values and linkages

        Args:
            instance: The instance of the class.
        """
        self._reset_values(instance)

    def _cast_to_type(self, value):
        """Verify the type of value assigned to the shadow field

        Args:
            value: The value to be assigned.

        Returns:
            The casted value.
        """
        # FIXME Verify that the value being assigned is compatible with the remote field
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self

        Args:
            value: The value to be converted to JSON.

        Raises:
            NotImplementedError: This method needs to be implemented in the derived class.

        """
        raise NotImplementedError

    def _reset_values(self, instance):
        """Reset all associated values and clean up dictionary items

        Args:
            instance: The instance of the class.
        """
        self.reference.value = None
        instance.__dict__.pop(self.field_name, None)
        instance.__dict__.pop(self.reference.field_name, None)
        self.reference.delete_cached_value(instance)


class Reference(FieldCacheMixin, Field):
    """
    A field representing a reference to another entity. This field is used to establish
    the reverse relationship to the remote entity.

    Args:
        to_cls (str or Entity): The target entity class or its name.
        **kwargs: Additional keyword arguments to be passed to the base `Field` class.
    """

    def __init__(self, to_cls, **kwargs):
        super().__init__(**kwargs)
        self._to_cls = to_cls

        self.relation = _ReferenceField(self)

    @property
    def to_cls(self):
        return self._to_cls

    def get_attribute_name(self):
        """Return formatted attribute name for the shadow field"""
        return "{}_{}".format(self.field_name, self.linked_attribute)

    def get_shadow_field(self):
        """Return shadow field
        Primarily used during Entity initialization to register shadow field"""
        return (self.attribute_name, self.relation)

    def get_cache_name(self):
        return self.field_name

    @property
    def linked_attribute(self):
        """Return linkage attribute to the target class

        This method is initially called from `__set_name__()` -> `get_attribute_name()`
        at which point, the `to_cls` has not been initialized properly. We simply default
        the linked attribute to 'id' in that case.

        Eventually, when setting value the first time, the `to_cls` entity is initialized
        and the attribute name is reset correctly.
        """
        if isinstance(self.to_cls, str):
            return "id"
        else:
            return id_field(self.to_cls).attribute_name

    def _resolve_to_cls(self, domain, to_cls, owner_cls):
        assert isinstance(self.to_cls, str)

        self._to_cls = to_cls

        # Refresh attribute name, now that we know `to_cls` Entity and it has been
        #   initialized with `id_field`
        self.attribute_name = self.get_attribute_name()

        # Reset the Shadow attribute's name
        self.relation = _ReferenceField(self)
        setattr(owner_cls, self.attribute_name, self.relation)
        self.relation.__set_name__(owner_cls, self.attribute_name)

        # Remove the earlier attribute if it is still attached
        old_attribute_name = "{}_{}".format(self.field_name, "id")
        if hasattr(owner_cls, old_attribute_name):
            delattr(owner_cls, old_attribute_name)

        # Update domain records because we enriched the class structure
        domain._replace_element_by_class(owner_cls)

    def __get__(self, instance, owner):
        """Retrieve associated objects"""
        reference_obj = None
        if hasattr(instance, "state_"):
            try:
                reference_obj = self.get_cached_value(instance)
            except KeyError:
                # Fetch target object by own Identifier
                id_field = self.get_attribute_name()

                id_value = None
                if hasattr(instance, id_field):
                    id_value = getattr(instance, id_field)

                if id_value:
                    reference_obj = self._fetch_objects(self.linked_attribute, id_value)
                    if reference_obj:
                        self._set_own_value(instance, reference_obj)
                    else:
                        # No Objects were found in the remote entity with this Entity's ID
                        pass

        return reference_obj

    def _fetch_objects(self, key, value):
        """Fetch Multiple linked objects"""
        return current_domain.repository_for(self.to_cls)._dao.find_by(**{key: value})

    def __set__(self, instance, value):
        """Override `__set__` to coordinate between relation field and its shadow attribute"""
        value = self._load(value)

        if value:
            # Check if the reference object has been saved. Otherwise, throw ValueError
            # FIXME not a comprehensive check. Should refer to state
            if getattr(value, id_field(value).field_name) is None:
                raise ValueError(
                    "Target Object must be saved before being referenced",
                    self.field_name,
                )
            else:
                self._set_own_value(instance, value)
                self._set_relation_value(
                    instance, getattr(value, self.linked_attribute)
                )
        else:
            self._reset_values(instance)

    def _set_own_value(self, instance, value):
        if value is None:
            instance.__dict__.pop(self.field_name, None)
            self.delete_cached_value(instance)
        else:
            instance.__dict__[self.field_name] = value
            self.set_cached_value(instance, value)

        # Mark Entity as Dirty
        if hasattr(instance, "state_"):
            instance.state_.mark_changed()

    def _set_relation_value(self, instance, value):
        if value is None:
            instance.__dict__.pop(self.attribute_name, None)
        else:
            instance.__dict__[self.attribute_name] = value

    def __delete__(self, instance):
        self._reset_values(instance)

    def _reset_values(self, instance):
        """Reset all associated values and clean up dictionary items"""
        self._set_own_value(instance, None)
        self._set_relation_value(instance, None)

    def _cast_to_type(self, value):
        # FIXME Assign value only of the correct type
        # if not isinstance(value, self.to_cls):
        #     self.fail('invalid', value=value)
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        raise NotImplementedError


class Association(FieldBase, FieldDescriptorMixin, FieldCacheMixin):
    """
    Represents an association between entities in a domain model.

    An association field allows one entity to reference another entity in the domain model.
    It provides methods to retrieve associated objects and handle changes in the association.

    Args:
        to_cls (class): The class of the target entity that this association references.
    """

    def __init__(self, to_cls, **kwargs):
        super().__init__(**kwargs)

        self._to_cls = to_cls

        # FIXME Find an elegant way to avoid these declarations in associations
        # Associations cannot be marked `required` or `unique`
        self.required = False
        self.unique = False

    @property
    def to_cls(self):
        return self._to_cls

    def _resolve_to_cls(self, domain, to_cls, owner_cls):
        """Resolves class references to actual class object.

        Called by the domain when a new element is registered,
        and its name matches `to_cls`
        """
        self._to_cls = to_cls

    def _cast_to_type(self, value):
        """Verify type of value assigned to the association field"""
        # FIXME Verify that the value being assigned is compatible with the associated Entity
        return value

    def _linked_attribute(self, owner):
        """Return linkage attribute to own entity's `id_field`

        FIXME Explore converting this method into an attribute, and treating it
        uniformly at `association` level.
        """
        return (
            utils.inflection.underscore(owner.__name__)
            + "_"
            + id_field(owner).attribute_name
        )

    def _linked_reference(self, owner):
        return utils.inflection.underscore(owner.__name__)

    def __get__(self, instance, owner):
        """Retrieve associated objects"""

        try:
            reference_obj = self.get_cached_value(instance)
        except KeyError:
            # Fetch target object by own Identifier
            id_value = getattr(instance, id_field(instance).field_name)
            reference_obj = self._fetch_objects(
                instance, self._linked_attribute(owner), id_value
            )

            self._set_own_value(instance, reference_obj)

        return reference_obj

    def _set_own_value(self, instance, value):
        instance.__dict__[self.field_name] = value
        self.set_cached_value(instance, value)

        # Mark Entity as Dirty
        if hasattr(instance, "state_"):
            instance.state_.mark_changed()

    @abstractmethod
    def _fetch_objects(self, instance, key, value):
        """Placeholder method for customized Association query methods"""

    @abstractmethod
    def as_dict(self):
        """Return JSON-compatible value of field"""

    def __set__(self, instance, value):
        """Set the value of the association field"""
        # Preserve heirarchy of entities.
        #
        #   Owner: is the entity that owns the association field
        #   Root: is the entity that is at the top of the hierarchy, an Aggregate Root
        if value is not None:
            items = value if isinstance(value, list) else [value]
            for item in items:
                item._set_root_and_owner(instance._root, instance)

    def __delete__(self, instance):
        """Cannot pop values for an association"""
        raise exceptions.NotSupportedError(
            "Object does not support the operation being performed",
            self.field_name,
        )

    def get_cache_name(self):
        return self.field_name

    @property
    def has_changed(self):
        return self.change is not None

    def _clone(self) -> "Association":
        """
        Clone the field with all its attributes.

        :return: Cloned Field object
        """
        return self


class HasOne(Association):
    """
    Represents an one-to-one association between an aggregate and its entities.

    This field is used to define a relationship where an aggregate is associated
    with at most one instance of a child entity.
    """

    def __set__(self, instance, value):
        """Setup relationship to be persisted/updated

        We track the change in the instance's `_temp_cache` to determine if the relationship
        has been added, updated, or deleted. We track two aspects: state and old value.

        For `HasOne`, there are three possible states:
        - ADDED: The relationship is being added for the first time
        - UPDATED: The relationship is being updated
        - DELETED: The relationship is being removed

        Of these, the old value is applicable for `UPDATED` and `DELETED` states.

        Also, we recursively remove child entities if they are associated with the old value.

        The `temp_cache` we set up here is eventually used by the `Repository` to determine
        the changes to be persisted.
        """
        # Accept dictionary values and convert them to Entity objects
        if isinstance(value, dict):
            value = self.to_cls(**value)

        super().__set__(instance, value)

        if value is not None and not isinstance(value, self.to_cls):
            raise ValidationError(
                {
                    "_entity": [
                        f"Value assigned to '{self.field_name}' is not of type '{self.to_cls.__name__}'"
                    ]
                }
            )

        # 1. Preserve parent linkage in child entity
        if value is not None:
            # This updates the parent's unique identifier in the child
            #   so that the foreign key relationship is preserved
            id_value = getattr(instance, id_field(instance).field_name)
            linked_attribute = self._linked_attribute(instance.__class__)
            if hasattr(value, linked_attribute):
                setattr(
                    value, linked_attribute, id_value
                )  # This overwrites any existing linkage, which is correct

            # Add the parent to the child entity cache
            # Temporarily set linkage to parent in child entity
            setattr(value, self._linked_reference(type(instance)), instance)

        # 2. Determine and store the change in the relationship
        current_value = getattr(instance, self.field_name)
        current_value_id = (
            getattr(current_value, id_field(current_value).field_name)
            if current_value
            else None
        )
        value_id = getattr(value, id_field(value).field_name) if value else None
        if current_value is None:
            # Entity was not associated earlier
            instance._temp_cache[self.field_name]["change"] = "ADDED"
        elif value is None:
            # Entity was associated earlier, but now being removed
            instance._temp_cache[self.field_name]["change"] = "DELETED"
            instance._temp_cache[self.field_name]["old_value"] = current_value
        elif current_value_id != value_id:
            # A New Entity is being associated replacing the old one
            instance._temp_cache[self.field_name]["change"] = "UPDATED"
            instance._temp_cache[self.field_name]["old_value"] = current_value
        elif current_value_id == value_id and value.state_.is_changed:
            # Entity was associated earlier, but now being updated
            instance._temp_cache[self.field_name]["change"] = "UPDATED"
        else:
            instance._temp_cache[self.field_name]["change"] = (
                None  # The same object has been assigned, No-Op
            )

        self._set_own_value(instance, value)

        # 3. Go Recursive and remove child entities if they are associated with the old value
        if instance._temp_cache[self.field_name]["change"] == "DELETED":
            old_value = instance._temp_cache[self.field_name]["old_value"]
            if has_association_fields(old_value):
                for field_name, field_obj in association_fields(old_value).items():
                    if isinstance(field_obj, HasMany):
                        field_obj.remove(old_value, getattr(old_value, field_name))
                    elif isinstance(field_obj, HasOne):
                        setattr(old_value, field_name, None)

        if instance._initialized and instance._root is not None:
            instance._root._postcheck()  # Trigger validations from the top

    def _fetch_objects(self, instance, key, identifier):
        """Fetch single linked object"""
        try:
            repo = current_domain.repository_for(self.to_cls)
            value = repo._dao.find_by(**{key: identifier})

            # Set up linkage with owner element
            setattr(
                value, key, identifier
            )  # This overwrites any existing linkage, which is correct

            return value
        except exceptions.ObjectNotFoundError:
            return None

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        if value is not None:
            return value.to_dict()


class HasMany(Association):
    """
    Represents a one-to-many association between two entities. This field is used to define a relationship where an
    aggregate has multiple instances of a chil entity.

    Args:
        to_cls (class): The class of the target entity.
        **kwargs: Additional keyword arguments to be passed to the base field class.
    """

    def __set__(self, instance, value):
        """This supports direct assignment of values to HasMany fields, like:
        `order.items = [item1, item2, item3]`
        """
        value = value if isinstance(value, list) else [value]

        # Accept dictionary values and convert them to Entity objects
        values = []
        for item in value:
            if isinstance(item, dict):
                values.append(self.to_cls(**item))
            else:
                values.append(item)

        super().__set__(instance, values)

        if value is not None:
            self.add(instance, values)

    def add(self, instance, items) -> None:
        """
        Available as `add_<HasMany Field Name>` method on the entity instance.

        This method adds one or more linked entities to the source entity. It also diffs the current value with the
        new value to determine the changes that need to be persisted.

        The method also takes care of the attributes of the linked entities, preparing them for persistence.

        Each linkage takes care of its own attributes, preparing them for persistence.
        One exception is deletion of an entity - all child entities have to be marked as removed.

        We track the change in the instance's `_temp_cache` to determine if the relationship
        has been added, updated, or deleted. We track each item's state and group the changes
        into three buckets:
        - ADDED: The relationship is being added for the first time
        - UPDATED: The relationship is being updated
        - DELETED: The relationship is being removed

        The `DELETED` objects are detected from the pool of new objects, but it is also possible to remove them
        directly with the `remove` method.

        The `temp_cache` we set up here is eventually used by the `Repository` to determine
        the changes to be persisted.

        Args:
            instance: The source entity instance.
            items: The linked entity or entities to be added.
        """
        super().__set__(instance, items)

        data = getattr(instance, self.field_name)

        # Convert a single item into a list of items, if necessary
        items = [items] if not isinstance(items, list) else items

        # Validate that all items are of the same type, and the correct type
        for item in items:
            if not isinstance(item, self.to_cls):
                raise ValidationError(
                    {
                        "_entity": [
                            f"Value assigned to '{self.field_name}' is not of type '{self.to_cls.__name__}'"
                        ]
                    }
                )

        current_value_ids = [
            getattr(value, id_field(value).field_name) for value in data
        ]

        # Remove items when set to empty
        if len(items) == 0 and len(current_value_ids) > 0:
            self.remove(instance, data)

        for item in items:
            # Items to add
            identity = getattr(item, id_field(item).field_name)
            if identity not in current_value_ids:
                # If the same item is added multiple times, the last item added will win
                instance._temp_cache[self.field_name]["added"][identity] = item

                setattr(
                    item,
                    self._linked_attribute(type(instance)),
                    getattr(instance, id_field(instance).field_name),
                )

                # Temporarily set linkage to parent in child entity
                setattr(item, self._linked_reference(type(instance)), instance)

                # Reset Cache
                self.delete_cached_value(instance)
            # Items to update
            elif (
                identity in current_value_ids
                and item.state_.is_persisted
                and item.state_.is_changed
            ):
                setattr(
                    item,
                    self._linked_attribute(type(instance)),
                    getattr(instance, id_field(instance).field_name),
                )

                # Temporarily set linkage to parent in child entity
                setattr(item, self._linked_reference(type(instance)), instance)

                instance._temp_cache[self.field_name]["updated"][identity] = item

                # Reset Cache
                self.delete_cached_value(instance)

        if instance._initialized and instance._root is not None:
            instance._root._postcheck()  # Trigger validations from the top

    def remove(self, instance, items) -> None:
        """
        Available as `add_<HasMany Field Name>` method on the entity instance.

        Remove one or more linked entities from the source entity.

        We also recursively remove child entities if they are associated with the removed value.

        Args:
            instance: The source entity instance.
            items: The linked entity or entities to be removed.
        """
        data = getattr(instance, self.field_name)

        # Convert a single item into a list of items, if necessary
        items = [items] if not isinstance(items, list) else items

        # Validate that all items are of the same type, and the correct type
        for item in items:
            if not isinstance(item, self.to_cls):
                raise ValidationError(
                    {
                        "_entity": [
                            f"Value assigned to '{self.field_name}' is not of type '{self.to_cls.__name__}'"
                        ]
                    }
                )

        current_value_ids = [
            getattr(value, id_field(value).field_name) for value in data
        ]

        for item in items:
            identity = getattr(item, id_field(item).field_name)
            if identity in current_value_ids:
                if identity not in instance._temp_cache[self.field_name]["removed"]:
                    instance._temp_cache[self.field_name]["removed"][identity] = item

                    # Reset Cache
                    self.delete_cached_value(instance)

            # Remove child entities
            if has_association_fields(item):
                for field_name, field_obj in association_fields(item).items():
                    if isinstance(field_obj, HasMany):
                        field_obj.remove(item, getattr(item, field_name))
                    elif isinstance(field_obj, HasOne):
                        setattr(item, field_name, None)

        if instance._initialized and instance._root is not None:
            instance._root._postcheck()  # Trigger validations from the top

    def _fetch_objects(self, instance, key, value) -> list:
        """
        Fetch linked entities.

        Args:
            instance: The source entity instance.
            key (str): The name of the attribute on the target entity that links back to the source entity.
            value: The value of the foreign key.

        Returns:
            list: A list of linked entity instances.
        """
        children_repo = current_domain.repository_for(self.to_cls)
        data = children_repo._dao.query.filter(**{key: value}).all().items

        # Set up linkage with owner element
        for item in data:
            setattr(item, key, value)

        # Add objects in temporary cache
        for _, item in instance._temp_cache[self.field_name]["added"].items():
            data.append(item)

        # Update objects from temporary cache if present
        updated_objects = []
        for value in data:
            identity = getattr(value, id_field(value).field_name)
            if identity in instance._temp_cache[self.field_name]["updated"]:
                updated_objects.append(
                    instance._temp_cache[self.field_name]["updated"][identity]
                )
            else:
                updated_objects.append(value)
        data = updated_objects

        # Remove objects marked as removed in temporary cache
        for _, item in instance._temp_cache[self.field_name]["removed"].items():
            # Retain data that is not among deleted items
            data[:] = [
                value
                for value in data
                if getattr(value, id_field(value).field_name)
                != getattr(item, id_field(item).field_name)
            ]

        return data

    def as_dict(self, value) -> list:
        """
        Return JSON-compatible value of self.

        Args:
            value: The value to be converted to a JSON-compatible format.

        Returns:
            list: A list of dictionaries representing the linked entities.
        """
        return [item.to_dict() for item in value]

    def get(self, instance, **kwargs):
        """Fetch a single linked entity based on the provided criteria.

        Available as `get_one_from_<HasMany Field Name>` method on the entity instance.

        Args:
            **kwargs: The filtering criteria.
        """
        data = self.filter(instance, **kwargs)

        if len(data) == 0:
            raise exceptions.ObjectNotFoundError(
                "No linked entities matching criteria found"
            )

        if len(data) > 1:
            raise exceptions.TooManyObjectsError(
                "Multiple linked entities matching criteria found"
            )

        return data[0]

    def filter(self, instance, **kwargs):
        """Filter the linked entities based on the provided criteria.

        Available as `filter_<HasMany Field Name>` method on the entity instance.

        Args:
            **kwargs: The filtering criteria.
        """
        data = getattr(instance, self.field_name)
        return [
            item
            for item in data
            if all(getattr(item, key) == value for key, value in kwargs.items())
        ]
