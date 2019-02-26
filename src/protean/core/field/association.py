from .base import Field
from .mixins import FieldCacheMixin

from protean.core import exceptions
from protean.utils import inflection


class ReferenceField(Field):
    """Shadow Attribute Field to back References"""

    def __init__(self, reference, **kwargs):
        """Accept reference field as a an attribute, otherwise is a straightforward field"""
        self.reference = reference
        super().__init__(**kwargs)

    def __set__(self, instance, value):
        """Override `__set__` to update relation field"""
        value = self._load(value)

        if value:
            instance.__dict__[self.field_name] = value

            # Fetch target object and refresh the reference field value
            reference_obj = self.reference.to_cls.find_by(
                **{self.reference.linked_attribute: value})
            if reference_obj:
                self.reference.value = reference_obj
                instance.__dict__[self.reference.field_name] = reference_obj
            else:
                # Object was not found in the database
                raise exceptions.ValueError(
                    "Target Object not found",
                    self.reference.field_name)
        else:
            self._reset_values(instance)

    def __delete__(self, instance):
        self._reset_values(instance)

    def _cast_to_type(self, value):
        """Verify type of value assigned to the shadow field"""
        # FIXME Verify that the value being assigned is compatible with the remote field
        return value

    def _reset_values(self, instance):
        """Reset all associated values and clean up dictionary items"""
        instance.__dict__.pop(self.field_name)
        instance.__dict__.pop(self.reference.field_name)
        self.reference.value = None
        self.value = None


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
        self.to_cls = to_cls
        self.via = via

        self.relation = ReferenceField(self)

    def get_attribute_name(self):
        """Return attribute name suffixed with via if defined, or `_id`"""
        return '{}_{}'.format(self.field_name, self.linked_attribute)

    def get_shadow_field(self):
        """Return shadow field
        Primarily used during Entity initialization to register shadow field"""
        return (self.attribute_name, self.relation)

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
            return 'id'
        else:
            return self.via or self.to_cls.id_field.attribute_name

    def _fetch_to_cls_from_registry(self, entity):
        """Private Method to fetch an Entity class from an entity's name

           FIXME Move this method into utils
        """
        # Defensive check to ensure we only process if `to_cls` is a string
        if isinstance(entity, str):
            from protean.core.repository import repo_factory  # FIXME Move to a better placement

            try:
                return repo_factory.get_entity(self.to_cls)
            except AssertionError:
                # Entity has not been registered (yet)
                # FIXME print a helpful debug message
                raise
        else:
            return self.to_cls

    def __set__(self, instance, value):
        """Override `__set__` to coordinate between relation field and its shadow attribute"""
        if isinstance(self.to_cls, str):
            self.to_cls = self._fetch_to_cls_from_registry(self.to_cls)

            # Refresh attribute name, now that we know `to_cls` Entity and it has been
            #   initialized with `id_field`
            self.attribute_name = self.get_attribute_name()

        value = self._load(value)

        if value:
            # Check if the reference object has been saved. Otherwise, throw ValueError
            if value.id is None:  # FIXME not a comprehensive check. Should refer to state
                raise ValueError(
                    "Target Object must be saved before being referenced",
                    self.field_name)
            else:
                self.relation.value = value.id
                instance.__dict__[self.field_name] = value
                instance.__dict__[self.attribute_name] = getattr(value, self.linked_attribute)
        else:
            self._reset_values(instance)

    def __delete__(self, instance):
        self._reset_values(instance)

    def _reset_values(self, instance):
        """Reset all associated values and clean up dictionary items"""
        self.value = None
        self.relation.value = None
        instance.__dict__.pop(self.field_name, None)
        instance.__dict__.pop(self.attribute_name, None)

    def _cast_to_type(self, value):
        if not isinstance(value, self.to_cls):
            self.fail('invalid', value=value)
        return value

    def get_cache_name(self):
        return self.name


class HasOne(FieldCacheMixin, Field):
    """
    Provide a HasOne relation to a remote entity.

    By default, the query will lookup an attribute of the form `<current_entity>_id`
    to fetch and populate. This behavior can be changed by using the `via` argument.
    """

    def __init__(self, to_cls, via=None, **kwargs):
        super().__init__(**kwargs)
        self.to_cls = to_cls
        self.via = via

    def __set__(self, instance, value):
        """Cannot set values through the HasOne association"""
        raise exceptions.NotSupportedError(
            "Object does not support the operation being performed",
            self.field_name
        )

    def _cast_to_type(self, value):
        """Verify type of value assigned to the association field"""
        # FIXME Verify that the value being assigned is compatible with the associated Entity
        return value

    def _linked_attribute(self, owner):
        """Choose the Linkage attribute between `via` and own entity's `id_field`

           FIXME Explore converting this method into an attribute, and treating it
           uniformly at `association` level.
        """
        return self.via or (inflection.underscore(owner.__name__) + '_id')

    def _fetch_to_cls_from_registry(self, entity):
        """Private Method to fetch an Entity class from an entity's name"""
        # Defensive check to ensure we only process if `to_cls` is a string
        if isinstance(entity, str):
            from protean.core.repository import repo_factory  # FIXME Move to a better placement

            try:
                return repo_factory.get_entity(self.to_cls)
            except AssertionError:
                # Entity has not been registered (yet)
                # FIXME print a helpful debug message
                raise
        else:
            return self.to_cls

    def __get__(self, instance, owner):
        """Retrieve associated objects"""

        # If `to_cls` was specified as a string, take this opportunity to fetch
        #   and update the correct entity class against it, if not already done
        if isinstance(self.to_cls, str):
            self.to_cls = self._fetch_to_cls_from_registry(self.to_cls)

        # Fetch target object by own Identifier
        id_value = getattr(instance, instance.id_field.field_name)
        reference_obj = self.to_cls.find_by(**{self._linked_attribute(owner): id_value})
        if reference_obj:
            self.value = reference_obj
            return reference_obj
        else:
            # No Objects were found in the remote entity with this Entity's ID
            return None
