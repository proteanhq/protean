import copy
import logging

from collections import defaultdict

from protean.core.field.base import FieldBase
from protean.exceptions import InvalidDataError, NotSupportedError, ValidationError

logger = logging.getLogger("protean.domain")

_FIELDS = "__container_fields__"


def fields(class_or_instance):
    """Return a tuple describing the fields of this dataclass.

    Accepts a dataclass or an instance of one. Tuple elements are of
    type Field.
    """

    # Might it be worth caching this, per class?
    try:
        fields_dict = getattr(class_or_instance, _FIELDS)
    except AttributeError:
        raise TypeError("must be called with a dataclass type or instance")

    return fields_dict


def has_fields(class_or_instance):
    """Check if Protean element encloses fields"""
    return hasattr(class_or_instance, _FIELDS)


def attributes(class_or_instance):
    attributes_dict = {}
    for _, field_obj in fields(class_or_instance).items():
        attributes_dict[field_obj.get_attribute_name()] = field_obj

    return attributes_dict


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

        # Gather fields in the order specified, starting with base classes
        fields_dict = {}

        # ... from base classes first
        for base in reversed(bases):
            if hasattr(base, _FIELDS):
                for field_name, field_obj in fields(base).items():
                    fields_dict[field_name] = field_obj

        # ... Apply own fields next
        for attr_name, attr_obj in attrs.items():
            if isinstance(attr_obj, FieldBase):
                fields_dict[attr_name] = attr_obj

        # Gather all non-field attributes
        dup_attrs = {
            attr_name: attr_obj
            for attr_name, attr_obj in attrs.items()
            if attr_name not in fields_dict
        }

        # Propagate `__classcell__` if present to the `type.__new__` call.
        # Failing to do so will result in a RuntimeError in Python 3.8.
        # https://docs.python.org/3/reference/datamodel.html#creating-the-class-object
        classcell = attrs.pop("__classcell__", None)
        if classcell is not None:
            dup_attrs["__classcell__"] = classcell

        # Insert fields in the order in which they were specified
        #   When field names overlap, the last specified field wins
        dup_attrs.update(fields_dict)

        # Store fields in a special field for later reference
        dup_attrs[_FIELDS] = fields_dict

        return super().__new__(mcs, name, bases, dup_attrs, **kwargs)


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
        for field_name in fields(self):
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
        return any(bool(getattr(self, field_name, None)) for field_name in fields(self))

    def __setattr__(self, name, value):
        if name in fields(self) or name in [
            "errors",
        ]:
            super().__setattr__(name, value)
        else:
            raise InvalidDataError({name: ["is invalid"]})

    def to_dict(self):
        """ Return data as a dictionary """
        return {
            field_name: field_obj.as_dict(getattr(self, field_name, None))
            for field_name, field_obj in fields(self).items()
        }

    def clone(self):
        """Deepclone the command"""
        return copy.deepcopy(self)

    @classmethod
    def _default_options(cls):
        # FIXME Raise exception
        # raise NotImplementedError
        return []
