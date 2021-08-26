import inspect


class Element:
    """Base class for all Protean elements"""

    pass


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


class OptionsMixin:
    def __init_subclass__(subclass) -> None:
        """Setup Options metadata on elements

        Args:
            subclass (Protean Element): Subclass to initialize with metadata
        """
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
        #   with the help of `_default_options()` method defined in the Element's Root.
        #   Element Roots are `Event`, `Subscriber`, `Repository`, and so on.
        for key, default in subclass._default_options():
            value = (
                hasattr(subclass.meta_, key) and getattr(subclass.meta_, key)
            ) or default
            setattr(subclass.meta_, key, value)
