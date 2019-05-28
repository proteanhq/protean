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
    - ``aggregate``: The aggregate associated with the repository
    """

    def __init__(self, entity_name, meta):
        self.aggregate = getattr(meta, 'aggregate', None)


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

    def add(self, aggregate):
        if self.uow:
            self.uow.register_new(aggregate)
        else:
            dao = self.domain.get_dao(self.meta_.aggregate)
            dao.save(aggregate)

        return aggregate

    def remove(self, aggregate):
        """Remove object to Repository"""

    def get(self, identifier):
        """Retrieve object from Repository"""

    def filter(self, specification):
        """Filter for objects that fit specification"""
