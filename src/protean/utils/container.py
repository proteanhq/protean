import logging
from typing import Any, ClassVar


logger = logging.getLogger(__name__)


class Element:
    """Base class for all Protean elements"""


class Options(dict):
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

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return []

    @classmethod
    def _set_defaults(cls):
        # Assign default options for remaining items
        #   with the help of `_default_options()` method defined in the Element's Root.
        #   Element Roots are `Event`, `Subscriber`, `Repository`, and so on.
        #
        # Explicit `None` is a valid value set for an option, so we don't discard it.
        for key, default in cls._default_options():
            if not hasattr(cls.meta_, key):
                setattr(cls.meta_, key, default)
