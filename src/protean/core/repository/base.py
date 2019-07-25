# Protean
from protean.core.exceptions import InvalidOperationError
from protean.core.field.association import HasMany


class _RepositoryMetaclass(type):
    """
    This base metaclass processes the class declaration and constructs a meta object that can
    be used to introspect the Repository class later. Specifically, it sets up a `meta_` attribute on
    the Repository to an instance of Meta, either the default of one that is defined in the
    Repository class.

    `meta_` is setup with these attributes:
        * `aggregate`: The aggregate associated with the repository
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize Repository MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of Repository
        # (excluding Repository class itself).
        parents = [b for b in bases if isinstance(b, _RepositoryMetaclass)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Remove `abstract` in base classes if defined
        for base in bases:
            if hasattr(base, 'Meta') and hasattr(base.Meta, 'abstract'):
                delattr(base.Meta, 'abstract')

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop('Meta', None)
        meta = attr_meta or getattr(new_class, 'Meta', None)
        setattr(new_class, 'meta_', RepositoryMeta(name, meta))

        return new_class


class RepositoryMeta:
    """ Metadata info for the RepositoryMeta.

    Options:
    - ``aggregate_cls``: The aggregate associated with the repository
    """

    def __init__(self, entity_name, meta):
        self.aggregate_cls = getattr(meta, 'aggregate_cls', None)


class BaseRepository(metaclass=_RepositoryMetaclass):
    """This class outlines the base repository functions,
    to be satisifed by all implementing repositories.

    It is also a marker interface for registering repository
    classes with the domain"""

    def __init__(self, domain, uow=None):
        self.domain = domain
        self.uow = uow

    def within(self, uow):
        self.uow = uow
        return self

    def add(self, aggregate):  # noqa: C901
        if self.uow:
            # Handle the aggregate changes first
            if aggregate.state_.is_persisted and aggregate.state_.is_changed:
                self.uow.register_update(aggregate)
            elif not aggregate.state_.is_persisted:
                self.uow.register_new(aggregate)
            else:
                pass  # Ignore if the same unchanged object is added again to the repository

            # Handle child object changes next
            for field_name, field in aggregate.meta_.declared_fields.items():
                if isinstance(field, HasMany):
                    has_many_field = getattr(aggregate, field_name)

                    for item in has_many_field._temp_cache['added']:
                        if item.state_.is_persisted and item.state_.is_changed:
                            self.uow.register_update(item)
                        elif not item.state_.is_persisted:
                            self.uow.register_new(item)
                        else:
                            pass  # Ignore if the same unchanged object is added again to the repository
                    has_many_field._temp_cache['added'] = list()  # Empty contents of `added` list

                    for item in has_many_field._temp_cache['removed']:
                        if item.state_.is_persisted:
                            self.uow.register_delete(item)
                    has_many_field._temp_cache['removed'] = list()  # Empty contents of `removed` list
        else:
            # Persist only if the aggregate object is new, or it has changed since last persistence
            if ((not aggregate.state_.is_persisted) or
                    (aggregate.state_.is_persisted and aggregate.state_.is_changed)):
                dao = self.domain.get_dao(self.meta_.aggregate_cls)
                dao.save(aggregate)

            # If there are HasMany fields in the aggregate, they may have
            #   child objects added/removed, but not yet persisted to the database.
            for field_name, field in aggregate.meta_.declared_fields.items():
                if isinstance(field, HasMany):
                    has_many_field = getattr(aggregate, field_name)

                    for item in has_many_field._temp_cache['added']:
                        dao = self.domain.get_dao(field.to_cls)
                        dao.save(item)
                    has_many_field._temp_cache['added'] = list()  # Empty contents of `added` list

                    for item in has_many_field._temp_cache['removed']:
                        dao = self.domain.get_dao(field.to_cls)
                        dao.delete(item)
                    has_many_field._temp_cache['removed'] = list()  # Empty contents of `removed` list

        return aggregate

    def remove(self, aggregate):
        """Remove object to Repository"""
        if self.uow:
            if not aggregate.state_.is_persisted:
                raise InvalidOperationError("Element has not been persisted yet")

            self.uow.register_delete(aggregate)
        else:
            dao = self.domain.get_dao(self.meta_.aggregate_cls)
            dao.delete(aggregate)

        return aggregate

    def get(self, identifier):
        """Retrieve object from Repository"""
        dao = self.domain.get_dao(self.meta_.aggregate_cls)
        return dao.get(identifier)

    def filter(self, specification):
        """Filter for objects that fit specification"""
