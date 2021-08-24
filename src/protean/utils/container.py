import copy
import inspect
import logging

from collections import defaultdict
from protean.core.field.association import Association

from protean.core.field.basic import Field
from protean.exceptions import InvalidDataError, NotSupportedError, ValidationError

logger = logging.getLogger("protean.domain")


class ContainerMeta(type):
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
        parents = [b for b in bases if isinstance(b, ContainerMeta)]
        if not parents:
            return super().__new__(mcs, name, bases, attrs)

        # Remove `abstract` in base classes if defined
        for base in bases:
            if hasattr(base, "Meta") and hasattr(base.Meta, "abstract"):
                delattr(base.Meta, "abstract")

        ##############
        # Load Options
        ##############
        # Gather `Meta` class/object if defined
        options = attrs.pop("Meta", None)
        if options and options.__qualname__.split(".")[-2] == name:
            # `Meta` has been defined in this class
            attrs["meta_"] = Options(options)
        else:
            attrs["meta_"] = Options()

        #############
        # Load Fields
        #############
        own_fields = {
            attr_name: attr_obj
            for attr_name, attr_obj in attrs.items()
            if isinstance(attr_obj, (Field, Association))
        }

        base_class_fields = {}
        for base in reversed(bases):
            if hasattr(base, "meta_") and hasattr(base.meta_, "declared_fields"):
                # FIXME Handle case of two diff identifiers in parent and child class
                # FIXME Add test case to check field ordering
                base_class_fields.update(
                    {
                        field_name: field_obj
                        for (
                            field_name,
                            field_obj,
                        ) in base.meta_.declared_fields.items()
                        if field_name not in attrs
                    }
                )

        all_fields = {**own_fields, **base_class_fields}

        for attr_name, attr_obj in all_fields.items():
            attrs[attr_name] = attr_obj
            attrs["meta_"].declared_fields[attr_name] = attr_obj

        new_class = super().__new__(mcs, name, bases, attrs, **kwargs)

        #################
        # Default options
        #################
        for key, default in new_class._default_options():
            value = (
                hasattr(attrs["meta_"], key) and getattr(attrs["meta_"], key)
            ) or default
            setattr(new_class.meta_, key, value)

        return new_class


class Options:
    """ Metadata info for the Container.

    Options:
    - ``abstract``: Indicates that this is an abstract entity (Ignores all other meta options)

    Also acts as a placeholder for generated entity fields like:

        :declared_fields: dict
            Any instances of `Field` included as attributes on either the class
            or on any of its superclasses will be include in this dictionary.
    """

    def __init__(self, opts=None):
        attributes = inspect.getmembers(opts, lambda a: not (inspect.isroutine(a)))
        for attr in attributes:
            if not (attr[0].startswith("__") and attr[0].endswith("__")):
                setattr(self, attr[0], attr[1])

        # Common Meta attributes
        self.abstract = getattr(opts, "abstract", None) or False

        # Initialize Options
        # FIXME Move this to be within the container
        self.declared_fields = {}

    @property
    def attributes(self):
        attributes_dict = {}
        for _, field_obj in self.declared_fields.items():
            attributes_dict[field_obj.get_attribute_name()] = field_obj

        return attributes_dict


class BaseContainer(metaclass=ContainerMeta):
    """The Base class for Protean-Compliant Data Containers.

    Provides helper methods to custom define attributes, and find attribute names
    during runtime.
    """

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

    @classmethod
    def _default_options(cls):
        # FIXME Raise exception
        # raise NotImplementedError
        return []
