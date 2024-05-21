from __future__ import annotations

import copy
import inspect
import logging

from collections import defaultdict
from typing import Any, Type, Union

from protean.exceptions import (
    IncorrectUsageError,
    InvalidDataError,
    NotSupportedError,
    ValidationError,
)
from protean.fields import Auto, Field, FieldBase, Reference, ValueObject
from protean.utils import generate_identity

from .reflection import _FIELDS, _ID_FIELD_NAME, attributes, declared_fields, fields

logger = logging.getLogger(__name__)


class Element:
    """Base class for all Protean elements"""


class Options:
    """Metadata info for the Container.

    Common options:
    - ``abstract``: Indicates that this is an abstract entity (Ignores all other meta options)
    """

    def __init__(self, opts: Union[dict, Type] = None) -> None:
        self._opts = set()

        if opts:
            if inspect.isclass(opts):
                attributes = inspect.getmembers(
                    opts, lambda a: not (inspect.isroutine(a))
                )
                for attr in attributes:
                    if not (attr[0].startswith("__") and attr[0].endswith("__")):
                        setattr(self, attr[0], attr[1])

            elif isinstance(opts, dict):
                for opt_name, opt_value in opts.items():
                    setattr(self, opt_name, opt_value)

        # Common Meta attributes
        self.abstract = getattr(opts, "abstract", None) or False

    def __setattr__(self, __name: str, __value: Any) -> None:
        # Ignore if `_opts` is being set
        if __name != "_opts":
            self._opts.add(__name)

        super().__setattr__(__name, __value)

    def __delattr__(self, __name: str) -> None:
        self._opts.discard(__name)

        super().__delattr__(__name)

    def __eq__(self, other) -> bool:
        """Equivalence check based only on data."""
        if type(other) is not type(self):
            return False

        return self.__dict__ == other.__dict__

    def __hash__(self) -> int:
        """Overrides the default implementation and bases hashing on values"""
        return hash(frozenset(self.__dict__.items()))

    def __add__(self, other: Options) -> None:
        new_options = copy.copy(self)
        for opt in other._opts:
            setattr(new_options, opt, getattr(other, opt))

        return new_options


class OptionsMixin:
    def __init_subclass__(subclass) -> None:
        """Setup Options metadata on elements

        Args:
            subclass (Protean Element): Subclass to initialize with metadata
        """
        super().__init_subclass__()

        # Retrieve inner Meta class
        # Gather `Meta` class/object if defined
        options = getattr(subclass, "Meta", None)

        # Ensure that options are defined in this element class
        #   and not in one of its base class, by checking if the parent of the
        #   inner Meta class is the subclass being initialized
        #
        # PEP-3155 https://www.python.org/dev/peps/pep-3155/
        #   `__qualname__` contains the Inner class name in the form of a dot notation:
        #   <OuterClass>.<InnerClass>.
        if options and options.__qualname__.split(".")[-2] == subclass.__name__:
            subclass.meta_ = Options(options)
        else:
            subclass.meta_ = Options()

        # Assign default options for remaining items
        subclass._set_defaults()

    @classmethod
    def _set_defaults(cls):
        # Assign default options for remaining items
        #   with the help of `_default_options()` method defined in the Element's Root.
        #   Element Roots are `Event`, `Subscriber`, `Repository`, and so on.
        for key, default in cls._default_options():
            value = (hasattr(cls.meta_, key) and getattr(cls.meta_, key)) or default
            setattr(cls.meta_, key, value)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


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

    def __init__(self, *template, **kwargs):  # noqa: C901
        """
        Initialise the container.

        During initialization, set value on fields if validation passes.

        This initialization technique supports keyword arguments as well as dictionaries. You
            can even use a template for initial data.
        """
        self._initialized = False

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
            try:
                setattr(self, field_name, val)
            except ValidationError as err:
                for field_name in err.messages:
                    self.errors[field_name].extend(err.messages[field_name])
            finally:
                loaded_fields.append(field_name)

        # Load Value Objects from associated fields
        #   This block will dynamically construct value objects from field values
        #   and associated the vo with the entity
        # If the value object was already provided, it will not be overridden.
        for field_name, field_obj in fields(self).items():
            if isinstance(field_obj, (ValueObject)) and not getattr(self, field_name):
                attrs = [
                    (embedded_field.field_name, embedded_field.attribute_name)
                    for embedded_field in field_obj.embedded_fields.values()
                ]
                values = {name: kwargs.get(attr) for name, attr in attrs}
                try:
                    value_object = field_obj.value_object_cls(**values)
                    # Set VO value only if the value object is not None/Empty
                    if value_object:
                        setattr(self, field_name, value_object)
                        loaded_fields.append(field_name)
                except ValidationError as err:
                    for sub_field_name in err.messages:
                        self.errors["{}_{}".format(field_name, sub_field_name)].extend(
                            err.messages[sub_field_name]
                        )

        # Load Identities
        for field_name, field_obj in declared_fields(self).items():
            if type(field_obj) is Auto and not field_obj.increment:
                if not getattr(self, field_obj.field_name, None):
                    setattr(self, field_obj.field_name, generate_identity())
                loaded_fields.append(field_obj.field_name)

        # Now load the remaining fields with a None value, which will fail
        # for required fields
        for field_name in fields(self):
            if field_name not in loaded_fields:
                setattr(self, field_name, None)

        self.defaults()

        self._initialized = True

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
        """Equivalence check for containers is based only on data.

        Two container objects are considered equal if they have the same data.
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
        """Return this object's truthiness to be `False`,
        if all its attributes evaluate to truthiness `False`
        """
        return any(bool(getattr(self, field_name, None)) for field_name in fields(self))

    def __setattr__(self, name, value):
        if (
            name in attributes(self)
            or name in fields(self)
            or name
            in [
                "errors",  # Errors in state transition
                "state_",  # Tracking dirty state of the entity
                "_temp_cache",  # Temporary cache (Assocations) for storing data befor persisting
                "_events",  # Temp placeholder for events raised by the entity
                "_initialized",  # Flag to indicate if the entity has been initialized
                "_root",  # Root entity in the hierarchy
                "_owner",  # Owner entity in the hierarchy
                "_disable_invariant_checks",  # Flag to disable invariant checks
            ]
            or name.startswith(("add_", "remove_"))
        ):
            super().__setattr__(name, value)
        else:
            raise InvalidDataError({name: ["is invalid"]})

    def to_dict(self):
        """Return data as a dictionary"""
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


class EventedMixin:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._events = []

    def raise_(self, event) -> None:
        self._events.append(event)


class IdentityMixin:
    def __init_subclass__(subclass) -> None:
        super().__init_subclass__()

        subclass.__set_id_field()

    @classmethod
    def __set_id_field(new_class):
        """Lookup the id field for this entity and assign"""
        # FIXME What does it mean when there are no declared fields?
        #   Does it translate to an abstract entity?
        try:
            id_field = next(
                field
                for _, field in declared_fields(new_class).items()
                if isinstance(field, (Field, Reference)) and field.identifier
            )

            setattr(new_class, _ID_FIELD_NAME, id_field.field_name)

            # If the aggregate/entity has been marked abstract,
            #   and contains an identifier field, raise exception
            if new_class.meta_.abstract and id_field:
                raise IncorrectUsageError(
                    {
                        "_entity": [
                            f"Abstract Aggregate `{new_class.__name__}` marked as abstract cannot have"
                            " identity fields"
                        ]
                    }
                )
        except StopIteration:
            # If no id field is declared then create one
            #   If the aggregate/entity is marked abstract,
            #   avoid creating an identifier field.
            if not new_class.meta_.abstract:
                new_class.__create_id_field()

    @classmethod
    def __create_id_field(new_class):
        """Create and return a default ID field that is Auto generated"""
        id_field = Auto(identifier=True)

        setattr(new_class, "id", id_field)

        # Set the name of the field on itself
        id_field.__set_name__(new_class, "id")

        # Set the name of the attribute on the class
        setattr(new_class, _ID_FIELD_NAME, id_field.field_name)

        # Add the attribute to _FIELDS for introspection
        field_objects = getattr(new_class, _FIELDS)
        field_objects["id"] = id_field
        setattr(new_class, _FIELDS, field_objects)
