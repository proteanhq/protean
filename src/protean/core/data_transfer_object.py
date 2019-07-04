"""Data Transfer Object Functionality and Classes"""
# Standard Library Imports
import copy
import logging

# Protean
from protean.core.exceptions import NotSupportedError, ValidationError
from protean.core.field.basic import Auto, Field
from protean.utils import inflection

logger = logging.getLogger('protean.core.data_transfer_object')


class _DataTransferObjectMetaclass(type):
    """
    This base metaclass processes the class declaration and constructs a meta object that can
    be used to introspect the DataTransferObject class later. Specifically, it sets up a `meta_` attribute on
    the DataTransferObject to an instance of Meta, either the default of one that is defined in the
    DataTransferObject class.

    `meta_` is setup with these attributes:
        * `declared_fields`: A dictionary that gives a list of any instances of `Field`
            included as attributes on either the class or on any of its superclasses
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize DataTransferObject MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of DataTransferObject
        # (excluding DataTransferObject class itself).
        parents = [b for b in bases if isinstance(b, _DataTransferObjectMetaclass)]
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
        setattr(new_class, 'meta_', DataTransferObjectMeta(name, meta))

        # Load declared fields
        new_class._load_fields(attrs)

        # Load declared fields from Base class, in case this Entity is subclassing another
        new_class._load_base_class_fields(bases, attrs)

        # Load list of Attributes from declared fields, depending on type of fields
        new_class._load_attributes()

        return new_class

    def _load_base_class_fields(new_class, bases, attrs):
        """If this class is subclassing another DataTransferObject, add that DataTransferObject's
        fields.  Note that we loop over the bases in *reverse*.
        This is necessary in order to maintain the correct order of fields.
        """
        for base in reversed(bases):
            if hasattr(base, 'meta_') and \
                    hasattr(base.meta_, 'declared_fields'):
                base_class_fields = {
                    field_name: field_obj for (field_name, field_obj)
                    in base.meta_.declared_fields.items()
                    if field_name not in attrs and not field_obj.identifier
                }
                new_class._load_fields(base_class_fields)

    def _load_fields(new_class, attrs):
        """Load field items into Class"""
        for attr_name, attr_obj in attrs.items():
            if isinstance(attr_obj, Field):
                setattr(new_class, attr_name, attr_obj)
                new_class.meta_.declared_fields[attr_name] = attr_obj

    def _load_attributes(new_class):
        """Load list of attributes from declared fields"""
        for field_name, field_obj in new_class.meta_.declared_fields.items():
            new_class.meta_.attributes[field_obj.get_attribute_name()] = field_obj


class DataTransferObjectMeta:
    """ Metadata info for the DataTransferObject.

    Options:
    - ``abstract``: Indicates that this is an abstract entity (Ignores all other meta options)
    - ``schema_name``: name of the schema (table/index/doc) used for persistence of this entity
        defaults to underscore version of the Entity name. Only considered if the DataTransferObject
        is to be persisted.
    - ``provider``: the name of the datasource associated with this
        DataTransferObject, default value is `default`. Only considered if the DataTransferObject is to be persisted.

    Also acts as a placeholder for generated entity fields like:

        :declared_fields: dict
            Any instances of `Field` included as attributes on either the class
            or on any of its superclasses will be include in this dictionary.
    """

    def __init__(self, entity_name, meta):
        self.abstract = getattr(meta, 'abstract', None) or False
        self.schema_name = (getattr(meta, 'schema_name', None) or
                            inflection.underscore(entity_name))
        self.provider = getattr(meta, 'provider', None) or 'default'

        # Initialize Options
        self.declared_fields = {}

    @property
    def unique_fields(self):
        """ Return the unique fields for this entity """
        return [(field_name, field_obj)
                for field_name, field_obj in self.declared_fields.items()
                if field_obj.unique]

    @property
    def auto_fields(self):
        return [(field_name, field_obj)
                for field_name, field_obj in self.declared_fields.items()
                if isinstance(field_obj, Auto)]

    @property
    def attributes(self):
        attributes_dict = {}
        for field_name, field_obj in self.declared_fields.items():
            attributes_dict[field_obj.get_attribute_name()] = field_obj

        return attributes_dict


class _FieldsCacheDescriptor:
    def __get__(self, instance, cls=None):
        if instance is None:
            return self
        res = instance.fields_cache = {}
        return res


class BaseDataTransferObject(metaclass=_DataTransferObjectMetaclass):
    """The Base class for Protean-Compliant Domain Data Transfer Objects.

    Provides helper methods to custom define attributes, and find attribute names
    during runtime.

    Basic Usage::

        @DataTransferObject
        class Address:
            unit = field.String()
            address = field.String(required=True, max_length=255)
            city = field.String(max_length=50)
            province = field.String(max_length=2)
            pincode = field.String(max_length=6)

    (or)

        class Address(BaseDataTransferObject):
            unit = field.String()
            address = field.String(required=True, max_length=255)
            city = field.String(max_length=50)
            province = field.String(max_length=2)
            pincode = field.String(max_length=6)

        domain.register_element(Address)

    If persistence is required, the model associated with this data transfer object is retrieved dynamically.
    The data transfer object may be persisted along with its related entity, or separately in which case its model is
    retrieved from the repository factory. Model is usually initialized with a live DB connection.
    """

    def __new__(cls, *args, **kwargs):
        if cls is BaseDataTransferObject:
            raise TypeError("BaseDataTransferObject cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *template, owner=None, **kwargs):
        """
        Initialise the data transfer object.

        During initialization, set value on fields if vaidation passes.

        This initialization technique supports keyword arguments as well as dictionaries. You
            can even use a template for initial data.
        """

        if self.meta_.abstract is True:
            raise NotSupportedError(
                f'{self.__class__.__name__} class has been marked abstract'
                f' and cannot be instantiated')

        self.errors = {}

        # Entity/Aggregate to which this Data Transfer Object is connected to
        self.owner = owner

        # Load the attributes based on the template
        loaded_fields = []
        for dictionary in template:
            if not isinstance(dictionary, dict):
                raise AssertionError(
                    f'Positional argument "{dictionary}" passed must be a dict.'
                    f'This argument serves as a template for loading common '
                    f'values.'
                )
            for field_name, val in dictionary.items():
                loaded_fields.append(field_name)
                setattr(self, field_name, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            loaded_fields.append(field_name)
            setattr(self, field_name, val)

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, field_obj in self.meta_.declared_fields.items():
            if field_name not in loaded_fields:
                setattr(self, field_name, None)

        # Raise any errors found during load
        if self.errors:
            raise ValidationError(self.errors)

        self.clean()

    @classmethod
    def build(cls, **values):
        assert all(attr in values
                   for attr in cls.meta_.declared_fields.keys())

        return cls(**values)

    def clean(self):
        """Placeholder method for validations.
        To be overridden in concrete Data Transfer Objects, when complex
        validations spanning multiple fields are required.
        """

    def __eq__(self, other):
        """Equaivalence check for data transfer objects is based only on data.

        Two Data Transfer Objects are considered equal if they have the same data.
        """
        if type(other) is not type(self):
            return False

        return self.to_dict() == other.to_dict()

    def __hash__(self):
        """Overrides the default implementation and bases hashing on values"""
        return hash(frozenset(self.to_dict().items()))

    def __repr__(self):
        """Friendly repr for Data Transfer Object"""
        return '<%s: %s>' % (self.__class__.__name__, self)

    def __str__(self):
        return '%s object (%s)' % (
            self.__class__.__name__,
            '{}'.format(self.to_dict())
        )

    def to_dict(self):
        """ Return data as a dictionary """
        return {field_name: getattr(self, field_name, None)
                for field_name in self.meta_.attributes}

    def clone(self):
        """Deepclone the data transfer object"""
        return copy.deepcopy(self)

    def _clone_with_values(self, **kwargs):
        """To be implemented in each data transfer object"""
        raise NotImplementedError
