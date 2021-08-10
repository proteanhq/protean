from abc import abstractmethod

from protean import exceptions, utils
from protean.globals import current_domain
from protean.utils import DomainObjects, fetch_element_cls_from_registry

from .base import Field
from .mixins import FieldCacheMixin, FieldDescriptorMixin


class _ReferenceField(Field):
    """Shadow Attribute Field to back References"""

    def __init__(self, reference, **kwargs):
        """Accept reference field as a an attribute, otherwise is a straightforward field"""
        self.reference = reference
        super().__init__(**kwargs)

    def __set__(self, instance, value):
        """Override `__set__` to update relation field and keep it in sync with the shadow
        attribute's value
        """
        value = self._load(value)

        if value:
            instance.__dict__[self.field_name] = value
        else:
            # Important to handle None assignment, and interpret it to mean resetting values
            self._reset_values(instance)

    def __delete__(self, instance):
        """Nullify values and linkages"""
        self._reset_values(instance)

    def _cast_to_type(self, value):
        """Verify type of value assigned to the shadow field"""
        # FIXME Verify that the value being assigned is compatible with the remote field
        return value

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        raise NotImplementedError

    def _reset_values(self, instance):
        """Reset all associated values and clean up dictionary items"""
        self.value = None
        self.reference.value = None
        instance.__dict__.pop(self.field_name, None)
        instance.__dict__.pop(self.reference.field_name, None)
        self.reference.delete_cached_value(instance)


class Reference(FieldCacheMixin, Field):
    """
    Provide a many-to-one relation by adding an attribute to the local entity
    to hold the remote value.

    By default ForeignKey will target the `id` column of the remote model but this
    behavior can be changed by using the ``via`` argument.
    """

    def __init__(self, to_cls, via=None, **kwargs):
        # FIXME ensure `via` argument is of type `str`
        super().__init__(**kwargs)
        self._to_cls = to_cls
        self.via = via

        self.relation = _ReferenceField(self)

    @property
    def to_cls(self):
        return self._to_cls

    def get_attribute_name(self):
        """Return attribute name suffixed with via if defined, or `_id`"""
        return "{}_{}".format(self.field_name, self.linked_attribute)

    def get_shadow_field(self):
        """Return shadow field
        Primarily used during Entity initialization to register shadow field"""
        return (self.attribute_name, self.relation)

    def get_cache_name(self):
        return self.field_name

    @property
    def linked_attribute(self):
        """Choose the Linkage attribute between `via` and designated `id_field` of the target class

        This method is initially called from `__set_name__()` -> `get_attribute_name()`
        at which point, the `to_cls` has not been initialized properly. We simply default
        the linked attribute to 'id' in that case.

        Eventually, when setting value the first time, the `to_cls` entity is initialized
        and the attribute name is reset correctly.
        """
        if isinstance(self.to_cls, str):
            return "id"
        else:
            return self.via or self.to_cls.meta_.id_field.attribute_name

    def _resolve_to_cls(self, instance):
        assert isinstance(self.to_cls, str)

        self._to_cls = fetch_element_cls_from_registry(
            self.to_cls, (DomainObjects.AGGREGATE, DomainObjects.ENTITY)
        )

        # Refresh attribute name, now that we know `to_cls` Entity and it has been
        #   initialized with `id_field`
        self.attribute_name = self.get_attribute_name()

        # Reset the Shadow attribute's name
        self.relation = _ReferenceField(self)
        setattr(instance.__class__, self.attribute_name, self.relation)
        self.relation.__set_name__(instance, self.attribute_name)

        # Remove the earlier attribute if it is still attached
        old_attribute_name = "{}_{}".format(self.field_name, "id")
        if hasattr(instance, old_attribute_name):
            delattr(instance, old_attribute_name)

        # Update domain records because we enriched the class structure
        current_domain._replace_element_by_class(instance.__class__)

    def __get__(self, instance, owner):
        """Retrieve associated objects"""

        # If `to_cls` was specified as a string, take this opportunity to fetch
        #   and update the correct entity class against it, if not already done
        if isinstance(self.to_cls, str):
            self._resolve_to_cls(instance)

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
        return current_domain.get_dao(self.to_cls).find_by(**{key: value})

    def __set__(self, instance, value):
        """Override `__set__` to coordinate between relation field and its shadow attribute"""
        if value:
            # If `to_cls` was specified as a string, take this opportunity to fetch
            #   and update the correct entity class against it, if not already done
            if isinstance(self.to_cls, str):
                self._resolve_to_cls(instance)

            value = self._load(value)

            if value:
                # Check if the reference object has been saved. Otherwise, throw ValueError
                # FIXME not a comprehensive check. Should refer to state
                if getattr(value, value.meta_.id_field.field_name) is None:
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


class Association(FieldDescriptorMixin, FieldCacheMixin):
    """Base class for all association classes"""

    def __init__(self, to_cls, via=None, **kwargs):
        super().__init__(**kwargs)

        self.to_cls = to_cls
        self.via = via

        # FIXME Refactor for general use across all types of associations. Currently used only with `HasOne`
        self.change = None  # Used to store type of change in the association
        self.change_old_value = None  # Used to preserve the old value that was removed

    def _cast_to_type(self, value):
        """Verify type of value assigned to the association field"""
        # FIXME Verify that the value being assigned is compatible with the associated Entity
        return value

    def _linked_attribute(self, owner):
        """Choose the Linkage attribute between `via` and own entity's `id_field`

        FIXME Explore converting this method into an attribute, and treating it
        uniformly at `association` level.
        """
        return self.via or (
            utils.inflection.underscore(owner.__name__)
            + "_"
            + owner.meta_.id_field.attribute_name
        )

    def __get__(self, instance, owner):
        """Retrieve associated objects"""

        # If `to_cls` was specified as a string, take this opportunity to fetch
        #   and update the correct entity class against it, if not already done
        if isinstance(self.to_cls, str):
            self.to_cls = fetch_element_cls_from_registry(
                self.to_cls, (DomainObjects.AGGREGATE, DomainObjects.ENTITY)
            )

            # FIXME Test that `to_cls` contains a corresponding `Reference` field

        try:
            reference_obj = self.get_cached_value(instance)
        except KeyError:
            # Fetch target object by own Identifier
            id_value = getattr(instance, instance.meta_.id_field.field_name)
            reference_obj = self._fetch_objects(
                instance, self._linked_attribute(owner), id_value
            )

            self._set_own_value(instance, reference_obj)

        return reference_obj

    def _set_own_value(self, instance, value):
        self.value = value
        instance.__dict__[self.field_name] = value
        self.set_cached_value(instance, value)

        # Mark Entity as Dirty
        if hasattr(instance, "state_"):
            instance.state_.mark_changed()

    @abstractmethod
    def _fetch_objects(self, instance, key, value):
        """Placeholder method for customized Association query methods"""
        raise NotImplementedError

    @abstractmethod
    def as_dict(self):
        """Return JSON-compatible value of field"""
        raise NotImplementedError

    def __set__(self, instance, value):
        """Cannot set values through an association"""
        raise exceptions.NotSupportedError(
            "Object does not support the operation being performed", self.field_name,
        )

    def __delete__(self, instance):
        """Cannot pop values for an association"""
        raise exceptions.NotSupportedError(
            "Object does not support the operation being performed", self.field_name,
        )

    def get_cache_name(self):
        return self.field_name

    @property
    def has_changed(self):
        return self.change is not None


class HasOne(Association):
    """
    Provide a HasOne relation to a remote entity.

    By default, the query will lookup an attribute of the form `<current_entity>_id`
    to fetch and populate. This behavior can be changed by using the `via` argument.
    """

    def __set__(self, instance, value):
        """Setup relationship to be persisted/updated"""
        # If `to_cls` was specified as a string, take this opportunity to fetch
        #   and update the correct entity class against it, if not already done
        if isinstance(self.to_cls, str):
            self.to_cls = fetch_element_cls_from_registry(
                self.to_cls, (DomainObjects.AGGREGATE, DomainObjects.ENTITY)
            )

            # FIXME Test that `to_cls` contains a corresponding `Reference` field

        if value is not None:
            # This updates the parent's unique identifier in the child
            #   so that the foreign key relationship is preserved
            id_value = getattr(instance, instance.meta_.id_field.field_name)
            linked_attribute = self._linked_attribute(instance.__class__)
            if hasattr(value, linked_attribute):
                setattr(
                    value, linked_attribute, id_value
                )  # This overwrites any existing linkage, which is correct

        current_value = getattr(instance, self.field_name)
        if current_value is None:
            self.change = "ADDED"
        elif value is None:
            self.change = "DELETED"
            self.change_old_value = self.value
        elif current_value.id != value.id:
            self.change = "UPDATED"
            self.change_old_value = self.value
        elif current_value.id == value.id and value.state_.is_changed:
            self.change = "UPDATED"
        else:
            self.change = None  # The same object has been assigned, No-Op

        self._set_own_value(instance, value)

    def _fetch_objects(self, instance, key, value):
        """Fetch single linked object"""
        try:
            return current_domain.get_dao(self.to_cls).find_by(**{key: value})
        except exceptions.ObjectNotFoundError:
            return None

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        if value is not None:
            return value.to_dict()


class HasMany(Association):
    """
    Provide a HasMany relation to a remote entity.

    By default, the query will lookup an attribute of the form `<current_entity>_id`
    to fetch and populate. This behavior can be changed by using the `via` argument.
    """

    def __init__(self, to_cls, via=None, **kwargs):
        super().__init__(to_cls, via=via, **kwargs)

        # `_temp_cache` is a data container for holding temporary
        #   It holds objects that have been added, but not yet persisted,
        #   as well as objects that have been removed, but are still
        #   present in the data store.
        #
        # The data set returned from Queryset is manipulated automatically
        #   to be up-to-date with temporary changes.
        self._temp_cache = {
            "added": {},
            "updated": {},
            "removed": {},
        }

    def add(self, instance, items):
        data = getattr(instance, self.field_name)

        # Convert a single item into a list of items, if necessary
        items = [items] if not isinstance(items, list) else items

        current_value_ids = [value.id for value in data]

        for item in items:
            # Items to add
            if item.id not in current_value_ids:
                # If the same item is added multiple times, the last item added will win
                instance._temp_cache[self.field_name]["added"][item.id] = item

                setattr(
                    item,
                    self._linked_attribute(type(instance)),
                    getattr(instance, instance.meta_.id_field.field_name),
                )

                # Reset Cache
                self.delete_cached_value(instance)
            # Items to update
            elif (
                item.id in current_value_ids
                and item.state_.is_persisted
                and item.state_.is_changed
            ):
                setattr(
                    item,
                    self._linked_attribute(type(instance)),
                    getattr(instance, instance.meta_.id_field.field_name),
                )

                instance._temp_cache[self.field_name]["updated"][item.id] = item

                # Reset Cache
                self.delete_cached_value(instance)

    def remove(self, instance, items):
        data = getattr(instance, self.field_name)

        # Convert a single item into a list of items, if necessary
        items = [items] if not isinstance(items, list) else items

        current_value_ids = [value.id for value in data]

        for item in items:
            if item.id in current_value_ids:
                if item.id not in instance._temp_cache[self.field_name]["removed"]:
                    instance._temp_cache[self.field_name]["removed"][item.id] = item

                    # Reset Cache
                    self.delete_cached_value(instance)

    def _fetch_objects(self, instance, key, value):
        """ Fetch linked entities.

        This method returns a well-formed query, containing the foreign-key constraint.
        """
        children_dao = current_domain.get_dao(self.to_cls)
        temp_data = children_dao.query.filter(**{key: value}).all().items

        # Add objects in temporary cache
        for _, item in instance._temp_cache[self.field_name]["added"].items():
            temp_data.append(item)

        # Update objects in temporary cache
        new_temp_data = []
        for value in temp_data:
            if value.id in instance._temp_cache[self.field_name]["updated"]:
                new_temp_data.append(
                    instance._temp_cache[self.field_name]["updated"][value.id]
                )
            else:
                new_temp_data.append(value)
        temp_data = new_temp_data

        # Remove objects in temporary cache
        for _, item in instance._temp_cache[self.field_name]["removed"].items():
            temp_data[:] = [value for value in temp_data if value.id != item.id]

        return temp_data

    def as_dict(self, value):
        """Return JSON-compatible value of self"""
        return [item.to_dict() for item in value]

    # FIXME This has been added for applications to explicit mark a `HasMany`
    #   as changed. Should be removed with better design.
    def _mark_changed(self, instance, item):
        instance._temp_cache[self.field_name]["updated"][item.id] = item

        # Reset Cache
        self.delete_cached_value(instance)
