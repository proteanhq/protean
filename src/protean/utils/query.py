"""Utility classes and methods for DB Adapters, Repositories and Query Constructors"""

import copy
import functools
import inspect
import logging
from typing import TYPE_CHECKING, Any, ClassVar, Iterator, cast

if TYPE_CHECKING:
    from protean.port.dao import BaseLookup

logger = logging.getLogger(__name__)


def subclasses(cls: type) -> Iterator[type]:
    """Iterator utility to loop and clear registered Lookups against a class"""
    yield cls
    for subclass in cls.__subclasses__():
        yield from subclasses(subclass)


class RegisterLookupMixin:
    """Helper Mixin to register Lookups to an Adapter"""

    class_lookups: ClassVar[dict[str, type["BaseLookup"]]]

    @classmethod
    def _get_lookup(cls, lookup_name: str) -> type["BaseLookup"] | None:
        return cls.get_lookups().get(lookup_name, None)

    @classmethod
    @functools.lru_cache(maxsize=None)
    def get_lookups(cls) -> dict[str, type["BaseLookup"]]:
        """Fetch all Lookups"""
        class_lookups = [
            parent.__dict__.get("class_lookups", {}) for parent in inspect.getmro(cls)
        ]
        return cls.merge_dicts(class_lookups)

    def get_lookup(self, lookup_name: str) -> type["BaseLookup"]:
        """Fetch Lookup by name"""
        from protean.port.dao import BaseLookup  # noqa: PLC0415

        lookup = self._get_lookup(lookup_name)

        # If unable to find Lookup, or if Lookup is the wrong class, raise Error
        if lookup is None or (
            lookup is not None and not issubclass(lookup, BaseLookup)
        ):
            raise NotImplementedError

        return lookup

    @staticmethod
    def merge_dicts(
        dicts: list[dict[str, type["BaseLookup"]]],
    ) -> dict[str, type["BaseLookup"]]:
        """
        Merge dicts in reverse to preference the order of the original list. e.g.,
        merge_dicts([a, b]) will preference the keys in 'a' over those in 'b'.
        """
        merged: dict[str, type["BaseLookup"]] = {}
        for d in reversed(dicts):
            merged.update(d)
        return merged

    @classmethod
    def _clear_cached_lookups(cls) -> None:
        for subclass in subclasses(cls):
            cast("type[RegisterLookupMixin]", subclass).get_lookups.cache_clear()

    @classmethod
    def register_lookup(
        cls,
        lookup: type["BaseLookup"],
        lookup_name: str | None = None,
    ) -> type["BaseLookup"]:
        """Register a Lookup to a class"""
        name: str = (
            cast(str, lookup.lookup_name) if lookup_name is None else lookup_name
        )
        if "class_lookups" not in cls.__dict__:
            cls.class_lookups = {}

        cls.class_lookups[name] = lookup
        cls._clear_cached_lookups()

        return lookup

    @classmethod
    def _delist_lookup(
        cls,
        lookup: type["BaseLookup"],
        lookup_name: str | None = None,
    ) -> None:
        """
        Remove given lookup from cls lookups. For use in tests only as it's
        not thread-safe.
        """
        name: str = (
            cast(str, lookup.lookup_name) if lookup_name is None else lookup_name
        )
        del cls.class_lookups[name]


class F:
    """Reference to another column of the same row, for use inside ``Q`` lookups.

    ``F`` lets a filter compare two columns of the same row instead of comparing
    a column against a literal value::

        # column against a literal
        query.filter(retry_count__lt=3)

        # column against another column
        query.filter(retry_count__lt=F("max_retries"))

    Only a bare column reference is supported. Arithmetic (``F("a") + 1``),
    function calls (``Lower(F("email"))``), and aggregations are intentionally
    out of scope.

    Adapter support: the in-memory and SQLAlchemy adapters resolve ``F`` to the
    referenced column natively. The Elasticsearch adapter raises
    ``NotImplementedError`` for ``F``-bearing predicates (column-to-column
    comparison there needs a Painless script query, which is not implemented);
    use the in-memory or SQLAlchemy backend for such filters.
    """

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"F({self.name!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, F) and self.name == other.name

    def __hash__(self) -> int:
        return hash(("F", self.name))


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

    def __init__(
        self,
        children: list[Any] | None = None,
        connector: str | None = None,
        negated: bool = False,
    ) -> None:
        """Construct a new Node. If no connector is given, use the default."""
        self.children: list[Any] = children[:] if children else []
        self.connector = connector or self.default
        self.negated = negated

    # Required because django.db.models.query_utils.Q. Q. __init__() is
    # problematic, but it is a natural Node subclass in all other respects.
    @classmethod
    def _new_instance(
        cls,
        children: list[Any] | None = None,
        connector: str | None = None,
        negated: bool = False,
    ) -> "Node":
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

    def __str__(self) -> str:
        template = "(NOT (%s: %s))" if self.negated else "(%s: %s)"
        return template % (self.connector, ", ".join(str(c) for c in self.children))

    def __repr__(self) -> str:
        return "<%s: %s>" % (self.__class__.__name__, self)

    def __deepcopy__(self, memodict: dict[int, Any]) -> "Node":
        obj = Node(connector=self.connector, negated=self.negated)
        obj.__class__ = self.__class__
        obj.children = copy.deepcopy(self.children, memodict)
        return obj

    def __len__(self) -> int:
        """Return the number of children this node has."""
        return len(self.children)

    def __bool__(self) -> bool:
        """Return whether or not this node has children."""
        return bool(self.children)

    def __contains__(self, other: Any) -> bool:
        """Return True if 'other' is a direct child of this instance."""
        return other in self.children

    def __eq__(self, other: object) -> bool:
        # Return NotImplemented (not AttributeError) for unrelated objects so
        # ``==`` falls back to identity and defensive equality checks stay safe.
        if not isinstance(other, Node):
            return NotImplemented
        return (
            self.__class__ == other.__class__
            and (self.connector, self.negated) == (other.connector, other.negated)
            and self.children == other.children
        )

    def add(self, data: Any, conn_type: str, squash: bool = True) -> Any:
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

    def negate(self) -> None:
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

    def __init__(
        self,
        *args: Any,
        _connector: str | None = None,
        _negated: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            children=[*args, *sorted(kwargs.items())],
            connector=_connector,
            negated=_negated,
        )

    def _combine(self, other: "Q", conn: str) -> "Q":
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

    def __or__(self, other: "Q") -> "Q":
        return self._combine(other, self.OR)

    def __and__(self, other: "Q") -> "Q":
        return self._combine(other, self.AND)

    def __invert__(self) -> "Q":
        obj = type(self)()
        obj.add(self, self.AND)
        obj.negate()
        return obj

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        """Deconstruct a Q Object"""
        path = "%s.%s" % (self.__class__.__module__, self.__class__.__name__)
        args: tuple[Any, ...] = ()
        kwargs: dict[str, Any] = {}

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
