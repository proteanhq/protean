"""Utility classes and methods for DB Adapters, Repositories and Query Constructors"""
import copy
import functools
import inspect
import logging

logger = logging.getLogger("protean.repository")


def subclasses(cls):
    """Iterator utility to loop and clear registered Lookups against a class"""
    yield cls
    for subclass in cls.__subclasses__():
        yield from subclasses(subclass)


class RegisterLookupMixin:
    """Helper Mixin to register Lookups to an Adapter"""

    @classmethod
    def _get_lookup(cls, lookup_name):
        return cls.get_lookups().get(lookup_name, None)

    @classmethod
    @functools.lru_cache(maxsize=None)
    def get_lookups(cls):
        """Fetch all Lookups"""
        class_lookups = [
            parent.__dict__.get("class_lookups", {}) for parent in inspect.getmro(cls)
        ]
        return cls.merge_dicts(class_lookups)

    def get_lookup(self, lookup_name):
        """Fetch Lookup by name"""
        from protean.port.dao import BaseLookup

        lookup = self._get_lookup(lookup_name)

        # If unable to find Lookup, or if Lookup is the wrong class, raise Error
        if lookup is None or (
            lookup is not None and not issubclass(lookup, BaseLookup)
        ):
            raise NotImplementedError

        return lookup

    @staticmethod
    def merge_dicts(dicts):
        """
        Merge dicts in reverse to preference the order of the original list. e.g.,
        merge_dicts([a, b]) will preference the keys in 'a' over those in 'b'.
        """
        merged = {}
        for d in reversed(dicts):
            merged.update(d)
        return merged

    @classmethod
    def _clear_cached_lookups(cls):
        for subclass in subclasses(cls):
            subclass.get_lookups.cache_clear()

    @classmethod
    def register_lookup(cls, lookup, lookup_name=None):
        """Register a Lookup to a class"""
        if lookup_name is None:
            lookup_name = lookup.lookup_name
        if "class_lookups" not in cls.__dict__:
            cls.class_lookups = {}

        cls.class_lookups[lookup_name] = lookup
        cls._clear_cached_lookups()

        return lookup

    @classmethod
    def _delist_lookup(cls, lookup, lookup_name=None):
        """
        Remove given lookup from cls lookups. For use in tests only as it's
        not thread-safe.
        """
        if lookup_name is None:
            lookup_name = lookup.lookup_name
        del cls.class_lookups[lookup_name]


class Node:
    """
    A class for storing a tree graph. Primarily used for filter constructs.

    A single internal node in the tree graph. A Node should be viewed as a
    connection (the root) with the children being either leaf nodes or other
    Node instances.
    """

    # Standard connector type. Clients usually won't use this at all and
    # subclasses will usually override the value.
    default = "DEFAULT"

    def __init__(self, children=None, connector=None, negated=False):
        """Construct a new Node. If no connector is given, use the default."""
        self.children = children[:] if children else []
        self.connector = connector or self.default
        self.negated = negated

    # Required because django.db.models.query_utils.Q. Q. __init__() is
    # problematic, but it is a natural Node subclass in all other respects.
    @classmethod
    def _new_instance(cls, children=None, connector=None, negated=False):
        """
        Create a new instance of this class when new Nodes (or subclasses) are
        needed in the internal code in this class. Normally, it just shadows
        __init__(). However, subclasses with an __init__ signature that aren't
        an extension of Node.__init__ might need to implement this method to
        allow a Node to create a new instance of them (if they have any extra
        setting up to do).
        """
        obj = Node(children, connector, negated)
        obj.__class__ = cls
        return obj

    def __str__(self):
        template = "(NOT (%s: %s))" if self.negated else "(%s: %s)"
        return template % (self.connector, ", ".join(str(c) for c in self.children))

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __deepcopy__(self, memodict):
        obj = Node(connector=self.connector, negated=self.negated)
        obj.__class__ = self.__class__
        obj.children = copy.deepcopy(self.children, memodict)
        return obj

    def __len__(self):
        """Return the number of children this node has."""
        return len(self.children)

    def __bool__(self):
        """Return whether or not this node has children."""
        return bool(self.children)

    def __contains__(self, other):
        """Return True if 'other' is a direct child of this instance."""
        return other in self.children

    def __eq__(self, other):
        return (
            self.__class__ == other.__class__
            and (self.connector, self.negated) == (other.connector, other.negated)
            and self.children == other.children
        )

    def add(self, data, conn_type, squash=True):
        """
        Combine this tree and the data represented by data using the
        connector conn_type. The combine is done by squashing the node other
        away if possible.

        This tree (self) will never be pushed to a child node of the
        combined tree, nor will the connector or negated properties change.

        Return a node which can be used in place of data regardless if the
        node other got squashed or not.

        If `squash` is False the data is prepared and added as a child to
        this tree without further logic.
        """
        if data in self.children:
            return data
        if not squash:
            self.children.append(data)
            return data
        if self.connector == conn_type:
            # We can reuse self.children to append or squash the node other.
            if (
                isinstance(data, Node)
                and not data.negated
                and (data.connector == conn_type or len(data) == 1)
            ):
                # We can squash the other node's children directly into this
                # node. We are just doing (AB)(CD) == (ABCD) here, with the
                # addition that if the length of the other node is 1 the
                # connector doesn't matter. However, for the len(self) == 1
                # case we don't want to do the squashing, as it would alter
                # self.connector.
                self.children.extend(data.children)
                return self
            else:
                # We could use perhaps additional logic here to see if some
                # children could be used for pushdown here.
                self.children.append(data)
                return data
        else:
            obj = self._new_instance(self.children, self.connector, self.negated)
            self.connector = conn_type
            self.children = [obj, data]
            return data

    def negate(self):
        """Negate the sense of the root connector."""
        self.negated = not self.negated


class Q(Node):
    """
    Encapsulate filters as objects that can then be combined logically (using
    `&` and `|`).
    """

    # Connection types
    AND = "AND"
    OR = "OR"
    default = AND
    conditional = True

    def __init__(self, *args, _connector=None, _negated=False, **kwargs):
        super().__init__(
            children=[*args, *sorted(kwargs.items())],
            connector=_connector,
            negated=_negated,
        )

    def _combine(self, other, conn):
        if not isinstance(other, Q):
            raise TypeError(other)

        # If the other Q() is empty, ignore it and just use `self`.
        if not other:
            return copy.deepcopy(self)
        # Or if this Q is empty, ignore it and just use `other`.
        elif not self:
            return copy.deepcopy(other)

        obj = type(self)()
        obj.connector = conn
        obj.add(self, conn)
        obj.add(other, conn)
        return obj

    def __or__(self, other):
        return self._combine(other, self.OR)

    def __and__(self, other):
        return self._combine(other, self.AND)

    def __invert__(self):
        obj = type(self)()
        obj.add(self, self.AND)
        obj.negate()
        return obj

    def deconstruct(self):
        """Deconstruct a Q Object"""
        path = "%s.%s" % (self.__class__.__module__, self.__class__.__name__)
        args, kwargs = (), {}

        if len(self.children) == 1 and not isinstance(self.children[0], Q):
            child = self.children[0]
            kwargs = {child[0]: child[1]}
        else:
            args = tuple(self.children)
            if self.connector != self.default:
                kwargs = {"_connector": self.connector}
        if self.negated:
            kwargs["_negated"] = True
        return path, args, kwargs
