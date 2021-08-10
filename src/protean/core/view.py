"""View Functionality and Classes"""
# Standard Library Imports
import copy
import logging

from collections import defaultdict
from uuid import uuid4

from protean.core.entity import _EntityState
from protean.core.field.association import Association, Reference
from protean.core.field.base import Field
from protean.core.field.basic import Auto, Identifier
from protean.core.field.embedded import ValueObject
from protean.exceptions import (
    ConfigurationError,
    IncorrectUsageError,
    NotSupportedError,
    ValidationError,
)
from protean.globals import current_domain
from protean.utils import (
    DomainObjects,
    IdentityStrategy,
    IdentityType,
    derive_element_class,
    inflection,
)

logger = logging.getLogger("protean.domain.view")


class _ViewMetaclass(type):
    """
    This base metaclass processes the class declaration and constructs a meta object that can
    be used to introspect the View class later. It sets up a `meta_` attribute on
    the View to an instance of ViewMeta, either the default or one that is defined within the
    View class.
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize View MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of View
        # (excluding View class itself).
        parents = [b for b in bases if isinstance(b, _ViewMetaclass)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Remove `abstract` if defined in base classes
        for base in bases:
            if hasattr(base, "Meta") and hasattr(base.Meta, "abstract"):
                delattr(base.Meta, "abstract")

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop(
            "Meta", None
        )  # Gather Metadata defined in inner `Meta` class
        view_meta = ViewMeta(name, attr_meta)  # Initialize the Metadata container
        setattr(
            new_class, "meta_", view_meta
        )  # Associate the Metadata container with new class

        # Load declared fields
        new_class._load_fields(attrs)

        # Load declared fields from Base class, in case this View is subclassing another
        new_class._load_base_class_fields(bases, attrs)

        # Lookup an already defined ID field or create an `Auto` field
        new_class._set_id_field()

        # Validate Field Types to be basic
        new_class._validate_for_basic_field_types()

        return new_class

    def _load_base_class_fields(new_class, bases, attrs):
        """If this class is subclassing another View, add that View's
        fields.  Note that we loop over the bases in *reverse*.
        This is necessary in order to maintain the correct order of fields.
        """
        for base in reversed(bases):
            if hasattr(base, "meta_") and hasattr(base.meta_, "declared_fields"):
                base_class_fields = {
                    field_name: field_obj
                    for (field_name, field_obj) in base.meta_.declared_fields.items()
                    if (field_name not in attrs and not field_obj.identifier)
                }
                new_class._load_fields(base_class_fields)

    def _load_fields(new_class, attrs):
        """Load field items into Class.

        This method sets up the primary attribute of an association.
        If Child class has defined an attribute so `parent = field.Reference(Parent)`, then `parent`
        is set up in this method, while `parent_id` is set up in `_set_up_reference_fields()`.
        """
        for attr_name, attr_obj in attrs.items():
            if isinstance(attr_obj, (Association, Field, Reference)):
                setattr(new_class, attr_name, attr_obj)
                new_class.meta_.declared_fields[attr_name] = attr_obj

    def _set_id_field(new_class):
        """Lookup the id field for this view and assign"""
        # FIXME What does it mean when there are no declared fields?
        #   Does it translate to an abstract view?
        if new_class.meta_.declared_fields:
            try:
                new_class.meta_.id_field = next(
                    field
                    for _, field in new_class.meta_.declared_fields.items()
                    if isinstance(field, (Field)) and field.identifier
                )
            except StopIteration:
                # If no id field is declared then create one
                logger.debug(
                    f"No explicit identifier was defined for {new_class.__name__}. "
                    f"Adding a default identifier called `id`..."
                )
                new_class._create_id_field()

    def _create_id_field(new_class):
        """Create and return a default ID field"""
        id_field = Identifier(identifier=True)

        setattr(new_class, "id", id_field)
        id_field.__set_name__(new_class, "id")

        # Ensure ID field is updated properly in Meta attribute
        new_class.meta_.declared_fields["id"] = id_field
        new_class.meta_.id_field = id_field

    def _validate_for_basic_field_types(new_class):
        for field_name, field_obj in new_class.meta_.declared_fields.items():
            if isinstance(field_obj, (Reference, Association, ValueObject)):
                raise IncorrectUsageError(
                    f"Views can only contain basic field types. "
                    f"Remove {field_name} ({field_obj.__class__.__name__}) from class {new_class.__name__}"
                )


class ViewMeta:
    """ Metadata info for the view.

    Options:
    - ``abstract``: Indicates that this is an abstract view (Ignores all other meta options)
    - ``schema_name``: name of the schema (table/index/doc) used for persistence of this view
        defaults to underscore version of the Entity name.
    - ``provider``: the name of the datasource associated with this
        view, default value is `default`.
    - ``cache``: the name of the cache associated with this view, default is `None`.
    - ``order_by``: default ordering of objects returned by filter queries.

    Also acts as a placeholder for generated view fields like:

        :declared_fields: dict
            Any instances of `Field` included as attributes on either the class
            or on any of its superclasses will be include in this dictionary.
        :id_field: protean.core.Field
            An instance of the field that will serve as the unique identifier for the view

    FIXME Make `ViewMeta` immutable
    """

    def __init__(self, view_name, meta):
        self.abstract = getattr(meta, "abstract", None) or False
        self.schema_name = getattr(meta, "schema_name", None) or inflection.underscore(
            view_name
        )
        self.provider = getattr(meta, "provider", None) or "default"
        self.cache = getattr(meta, "cache", None) or None
        self.model = getattr(meta, "model", None)

        # `order_by` can be provided either as a string or a tuple
        ordering = getattr(meta, "order_by", ())
        if isinstance(ordering, str):
            self.order_by = (ordering,)
        else:
            self.order_by = tuple(ordering)

        # Initialize Options
        self.declared_fields = {}
        self.value_object_fields = {}
        self.reference_fields = {}
        self.id_field = None

    @property
    def mandatory_fields(self):
        """ Return the mandatory fields for this view """
        return {
            field_name: field_obj
            for field_name, field_obj in self.attributes.items()
            if not isinstance(field_obj, Association) and field_obj.required
        }

    @property
    def unique_fields(self):
        """ Return the unique fields for this view """
        return {
            field_name: field_obj
            for field_name, field_obj in self.attributes.items()
            if not isinstance(field_obj, Association) and field_obj.unique
        }

    @property
    def auto_fields(self):
        return {
            field_name: field_obj
            for field_name, field_obj in self.declared_fields.items()
            if isinstance(field_obj, Auto)
        }

    @property
    def attributes(self):
        attributes_dict = {}
        for _, field_obj in self.declared_fields.items():
            attributes_dict[field_obj.get_attribute_name()] = field_obj

        return attributes_dict


class BaseView(metaclass=_ViewMetaclass):
    """The Base class for Protean-Compliant Domain Views."""

    element_type = DomainObjects.VIEW

    def __init__(self, *template, raise_errors=True, **kwargs):  # noqa: C901
        """
        Initialise the view object.

        During initialization, set value on fields if validation passes.

        This initialization technique supports keyword arguments as well as dictionaries. The objects initialized
        in the following example have the same structure::

            user1 = User({'first_name': 'John', 'last_name': 'Doe'})

            user2 = User(first_name='John', last_name='Doe')

        You can also specify a template for initial data and override specific attributes::

            base_user = User({'age': 15})

            user = User(base_user.to_dict(), first_name='John', last_name='Doe')
        """

        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        self.errors = defaultdict(list)
        self.raise_errors = raise_errors

        # Set up the storage for instance state
        self.state_ = _EntityState()

        # Load the attributes based on the template
        loaded_fields = []
        for dictionary in template:
            if not isinstance(dictionary, dict):
                raise AssertionError(
                    f'Positional argument "{dictionary}" passed must be a dict.'
                    f"This argument serves as a template for loading common "
                    f"values.",
                )
            for field_name, val in dictionary.items():
                if field_name not in kwargs:
                    kwargs[field_name] = val

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            loaded_fields.append(field_name)
            try:
                setattr(self, field_name, val)
            except ValidationError as err:
                for field_name in err.messages:
                    self.errors[field_name].extend(err.messages[field_name])

        # Generate values for Auto fields
        for field_name, field_obj in self.meta_.declared_fields.items():
            if isinstance(field_obj, Auto):
                setattr(self, field_name, self.generate_identity())
                loaded_fields.append(self.meta_.id_field.field_name)

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name, _ in self.meta_.declared_fields.items():
            if field_name not in loaded_fields:
                try:
                    setattr(self, field_name, None)
                except ValidationError as err:
                    for field_name in err.messages:
                        self.errors[field_name].extend(err.messages[field_name])

        for field_name, _ in self.meta_.attributes.items():
            if field_name not in loaded_fields and not hasattr(self, field_name):
                setattr(self, field_name, None)

        self.defaults()

        # `clean()` will return a `defaultdict(list)` if errors are to be raised
        custom_errors = self.clean() or {}
        for field in custom_errors:
            self.errors[field].extend(custom_errors[field])

        # Raise any errors found during load
        if self.errors and self.raise_errors:
            logger.error(self.errors)
            raise ValidationError(self.errors)

    def defaults(self):
        """Placeholder method for defaults.
        To be overridden in concrete Containers, when an attribute's default depends on other attribute values.
        """

    def clean(self):
        """Placeholder method for validations.
        To be overridden in concrete Containers, when complex validations spanning multiple fields are required.
        """
        return defaultdict(list)

    # FIXME DRY this method
    @classmethod
    def generate_identity(cls):
        """Generate Unique Identifier, based on configured strategy"""
        if current_domain.config["IDENTITY_STRATEGY"] == IdentityStrategy.UUID.value:
            if current_domain.config["IDENTITY_TYPE"] == IdentityType.INTEGER.value:
                return uuid4().int
            elif current_domain.config["IDENTITY_TYPE"] == IdentityType.STRING.value:
                return str(uuid4())
            elif current_domain.config["IDENTITY_TYPE"] == IdentityType.UUID.value:
                return uuid4()
            else:
                raise ConfigurationError(
                    f'Unknown Identity Type {current_domain.config["IDENTITY_TYPE"]}'
                )

        return None  # Database will generate the identity

    def __eq__(self, other):
        """Equivalence check to be based only on Identity"""

        # FIXME Enhanced Equality Checks
        #   * Ensure IDs have values and both of them are not null
        #   * Ensure that the ID is of the right type
        #   * Ensure that Objects belong to the same `type`
        #   * Check Reference equality

        # FIXME Check if `==` and `in` operator work with __eq__

        if type(other) is type(self):
            self_id = getattr(self, self.meta_.id_field.field_name)
            other_id = getattr(other, other.meta_.id_field.field_name)

            return self_id == other_id

        return False

    def __hash__(self):
        """Overrides the default implementation and bases hashing on identity"""

        # FIXME Add Object Class Type to hash
        return hash(getattr(self, self.meta_.id_field.field_name))

    def _update_data(self, *data_dict, **kwargs):
        """
        A private method to process and update view values correctly.

        :param data: A dictionary of values to be updated for the view
        :param kwargs: keyword arguments with key-value pairs to be updated
        """

        # Load each of the fields given in the data dictionary
        self.errors = {}

        for data in data_dict:
            if not isinstance(data, dict):
                raise AssertionError(
                    f'Positional argument "{data}" passed must be a dict.'
                    f"This argument serves as a template for loading common "
                    f"values.",
                )
            for field_name, val in data.items():
                setattr(self, field_name, val)

        # Now load against the keyword arguments
        for field_name, val in kwargs.items():
            setattr(self, field_name, val)

        # Raise any errors found during update
        if self.errors:
            logger.error(self.errors)
            raise ValidationError(self.errors)

    def to_dict(self):
        """ Return view data as a dictionary """
        return {
            field_name: getattr(self, field_name, None)
            for field_name, field_obj in self.meta_.declared_fields.items()
        }

    def __repr__(self):
        """Friendly repr for Entity"""
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self):
        identifier = getattr(self, self.meta_.id_field.field_name)
        return "%s object (%s)" % (
            self.__class__.__name__,
            "{}: {}".format(self.meta_.id_field.field_name, identifier),
        )

    def clone(self):
        """Deepclone the view, but reset state"""
        clone_copy = copy.deepcopy(self)
        clone_copy.state_ = _EntityState()

        return clone_copy


def view_factory(element_cls, **kwargs):
    element_cls = derive_element_class(element_cls, BaseView, **kwargs)

    if element_cls.meta_.abstract is True:
        raise NotSupportedError(
            f"{element_cls.__name__} class has been marked abstract"
            f" and cannot be instantiated"
        )

    element_cls.meta_.provider = (
        kwargs.pop("provider", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.provider)
        or "default"
    )
    element_cls.meta_.cache = (
        kwargs.pop("cache", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.cache)
        or None
    )
    element_cls.meta_.model = (
        kwargs.pop("model", None)
        or (hasattr(element_cls, "meta_") and element_cls.meta_.model)
        or None
    )

    if element_cls.meta_.provider and element_cls.meta_.cache:
        raise NotSupportedError(
            f"{element_cls.__name__} view can be persisted in"
            f"either a database or a cache, but not both"
        )

    return element_cls
