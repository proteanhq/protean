import copy
import inspect
import logging

from collections import defaultdict
from typing import Any, Dict

from protean.core.field.basic import Field
from protean.exceptions import InvalidDataError, NotSupportedError, ValidationError

logger = logging.getLogger("protean.domain")


class _ContainerMetaclass(type):
    """
    This base metaclass processes the class declaration and
    constructs a meta object that can be used to introspect
    the concrete Container class later.

    It also sets up a `meta_` attribute on the concrete class
    to an instance of Meta, either the default of one that is
    defined in the concrete class.
    """

    def __new__(mcs, name, bases, attrs, **kwargs):
        """Initialize Container MetaClass and load attributes"""

        # Ensure initialization is only performed for subclasses of Container
        # (excluding Container class itself).
        parents = [b for b in bases if isinstance(b, _ContainerMetaclass)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Remove `abstract` in base classes if defined
        for base in bases:
            if hasattr(base, "Meta") and hasattr(base.Meta, "abstract"):
                delattr(base.Meta, "abstract")

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        # Gather `Meta` class/object if defined
        attr_meta = attrs.pop("Meta", None)
        meta = attr_meta or getattr(new_class, "Meta", None)
        setattr(new_class, "meta_", ContainerMeta(meta))

        # Load declared fields
        new_class._load_fields(attrs)

        # Load declared fields from Base class, in case this Entity is subclassing another
        new_class._load_base_class_fields(bases, attrs)

        return new_class

    def _load_base_class_fields(new_class, bases, attrs):
        """If this class is subclassing another Container, add that Container's
        fields.  Note that we loop over the bases in *reverse*.
        This is necessary in order to maintain the correct order of fields.
        """
        for base in reversed(bases):
            if hasattr(base, "meta_") and hasattr(base.meta_, "declared_fields"):
                base_class_fields = {
                    field_name: field_obj
                    for (field_name, field_obj) in base.meta_.declared_fields.items()
                    if field_name not in attrs and not field_obj.identifier
                }
                new_class._load_fields(base_class_fields)

    def _load_fields(new_class, attrs):
        """Load field items into Class"""
        for attr_name, attr_obj in attrs.items():
            if isinstance(attr_obj, Field):
                setattr(new_class, attr_name, attr_obj)
                new_class.meta_.declared_fields[attr_name] = attr_obj


class ContainerMeta:
    """ Metadata info for the Container.

    Options:
    - ``abstract``: Indicates that this is an abstract entity (Ignores all other meta options)

    Also acts as a placeholder for generated entity fields like:

        :declared_fields: dict
            Any instances of `Field` included as attributes on either the class
            or on any of its superclasses will be include in this dictionary.
    """

    def __init__(self, meta):
        attributes = inspect.getmembers(meta, lambda a: not (inspect.isroutine(a)))
        for attr in attributes:
            if not (attr[0].startswith("__") and attr[0].endswith("__")):
                setattr(self, attr[0], attr[1])

        # Common Meta attributes
        self.abstract = getattr(meta, "abstract", None) or False
        self.version = 1

        # Initialize Options
        # FIXME Move this to be within the container
        self.declared_fields = {}

    @property
    def mandatory_fields(self):
        """ Return the mandatory fields for this entity """
        return {
            field_name: field_obj
            for field_name, field_obj in self.attributes.items()
            if field_obj.required
        }

    @property
    def attributes(self):
        attributes_dict = {}
        for field_name, field_obj in self.declared_fields.items():
            attributes_dict[field_obj.get_attribute_name()] = field_obj

        return attributes_dict


class BaseContainer(metaclass=_ContainerMetaclass):
    """The Base class for Protean-Compliant Data Containers.

    Provides helper methods to custom define attributes, and find attribute names
    during runtime.
    """

    # Placeholder for definition custom Element options. Overridden at Element Class level.
    META_OPTIONS = []

    def __new__(cls, *args, **kwargs):
        if cls is BaseContainer:
            raise TypeError("BaseContainer cannot be instantiated")
        return super().__new__(cls)

    def __init__(self, *template, **kwargs):
        """
        Initialise the container.

        During initialization, set value on fields if validation passes.

        This initialization technique supports keyword arguments as well as dictionaries. You
            can even use a template for initial data.
        """

        if self.meta_.abstract is True:
            raise NotSupportedError(
                f"{self.__class__.__name__} class has been marked abstract"
                f" and cannot be instantiated"
            )

        self.errors = defaultdict(list)

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

        self.defaults()

        # `clean()` will return a `defaultdict(list)` if errors are to be raised
        custom_errors = self.clean() or {}
        for field in custom_errors:
            self.errors[field].extend(custom_errors[field])

        # Raise any errors found during load
        if self.errors:
            logger.error(self.errors)
            raise ValidationError(self.errors)

    @classmethod
    def build(cls, **values):
        if values:
            assert all(
                attr in list(cls.meta_.declared_fields.keys()) for attr in values.keys()
            )

        return cls(**values)

    def defaults(self):
        """Placeholder method for defaults.
        To be overridden in concrete Containers, when an attribute's default depends on other attribute values.
        """

    def clean(self):
        """Placeholder method for validations.
        To be overridden in concrete Containers, when complex validations spanning multiple fields are required.
        """
        return defaultdict(list)

    def __eq__(self, other):
        """Equivalence check for commands is based only on data.

        Two Commands are considered equal if they have the same data.
        """
        if type(other) is not type(self):
            return False

        return self.to_dict() == other.to_dict()

    def __hash__(self):
        """Overrides the default implementation and bases hashing on values"""
        return hash(frozenset(self.to_dict().items()))

    def __repr__(self):
        """Friendly repr for Command"""
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __str__(self):
        return "%s object (%s)" % (
            self.__class__.__name__,
            "{}".format(self.to_dict()),
        )

    def __bool__(self):
        """ Return this object's truthiness to be `False`,
        if all its attributes evaluate to truthiness `False`
        """
        return any(
            bool(getattr(self, field_name, None))
            for field_name in self.meta_.attributes
        )

    def __setattr__(self, name, value):
        if name in self.meta_.declared_fields or name in [
            "errors",
        ]:
            super().__setattr__(name, value)
        else:
            raise InvalidDataError({name: ["is invalid"]})

    def to_dict(self):
        """ Return data as a dictionary """
        return {
            field_name: field_obj.as_dict(getattr(self, field_name, None))
            for field_name, field_obj in self.meta_.attributes.items()
        }

    def clone(self):
        """Deepclone the command"""
        return copy.deepcopy(self)

    def _clone_with_values(self, **kwargs):
        """To be implemented in each command"""
        raise NotImplementedError

    @classmethod
    def _extract_options(cls, **opts):
        """A stand-in method for setting customized options on the Domain Element

        Empty by default. To be overridden in each Element that expects or needs
        specific options.
        """
        for key, default in cls.META_OPTIONS:
            setattr(cls.meta_, key, cls._derive_preference(opts, key, default))

    @classmethod
    def _derive_preference(cls, kwargs: Dict, key: str, default: Any) -> Any:
        """A common method to pop an element's preference from multiple sources

        Args:
            kwargs (Dict): Explicit options provided for element
            element_cls (Any): The Domain Element to which options may be attached
            key (str): The attribute to derive
            default (Any): The default if no options are set

        Returns:
            Any: The attribute value
        """
        return (
            kwargs.pop(key, None)
            or (hasattr(cls.meta_, key) and getattr(cls.meta_, key))
            or default
        )
