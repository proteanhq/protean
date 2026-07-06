import copy
import logging
from typing import Any, Callable, ClassVar


logger = logging.getLogger(__name__)


class DerivedDefault:
    """Marker for a default option value that must be computed from the element
    class rather than being a static literal (e.g. a ``schema_name`` derived
    from the class name).

    ``_default_options`` is declarative *data* (a class attribute), so any
    per-class value is expressed as ``DerivedDefault(lambda cls: ...)`` and
    resolved by :meth:`OptionsMixin._set_defaults`. This keeps option defaults
    out of a class-definition-time method call.
    """

    __slots__ = ("fn",)

    def __init__(self, fn: Callable[[type["OptionsMixin"]], Any]) -> None:
        self.fn = fn

    def __call__(self, cls: type) -> Any:
        return self.fn(cls)


class Element:
    """Base class for all Protean elements"""


class Options(dict[str, Any]):
    """Metadata info for the Container.

    Common options:
    - ``abstract``: Indicates that this is an abstract entity (Ignores all other meta options)
    """

    def __init__(self, opts: dict[str, str | bool | None] | None = {}) -> None:
        super().__init__()

        if opts is None:
            opts = {}
        else:
            try:
                opts = dict(opts)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid options `{opts}`. Must be a dict.")

        self.update(opts)
        self["abstract"] = opts.get("abstract", None) or False

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(f"'Options' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self[name]
        except KeyError:
            raise AttributeError(f"'Options' object has no attribute '{name}'")

    def __add__(self, other: "Options") -> "Options":
        new_options = self.__class__(self)
        new_options.update(other)
        return new_options


class OptionsMixin:
    meta_: ClassVar["Options"]

    def __init_subclass__(cls) -> None:
        """Setup Options metadata on elements

        Args:
            cls (Protean Element): Subclass to initialize with metadata
        """
        if not hasattr(cls, "meta_"):
            setattr(cls, "meta_", Options())

        # Assign default options
        cls._set_defaults()

        super().__init_subclass__()

    # Declarative default options, keyed by option name. Element Roots
    # (``Aggregate``, ``Repository``, ``Subscriber``, ...) override this with
    # their own defaults. Per-class values (e.g. a schema name derived from the
    # class name) are wrapped in :class:`DerivedDefault` and resolved in
    # :meth:`_set_defaults`. This is data, not a method, so nothing element-
    # specific runs at class-definition time.
    _default_options: ClassVar[list[tuple[str, Any]]] = []

    @classmethod
    def _set_defaults(cls) -> None:
        # Assign default options for remaining items from the declarative
        #   `_default_options` defined in the Element's Root.
        #
        # Explicit `None` is a valid value set for an option, so we don't discard it.
        for key, default in cls._default_options:
            if not hasattr(cls.meta_, key):
                value = default(cls) if isinstance(default, DerivedDefault) else default
                # `_default_options` is now shared class data, so a mutable
                # literal default (e.g. `[]`, `{}`) is a single object across
                # every element class. Copy it before assigning so one class's
                # `meta_` can never alias another's (the old classmethod form
                # returned a fresh literal on each call).
                if isinstance(value, (list, dict, set)):
                    value = copy.copy(value)
                setattr(cls.meta_, key, value)

        # Universal option: `deprecated` defaults to None for all elements
        if not hasattr(cls.meta_, "deprecated"):
            cls.meta_.deprecated = None
