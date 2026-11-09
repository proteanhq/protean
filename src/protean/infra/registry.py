"""One registry per port, mapping an adapter name to its class.

An adapter package registers a name with a dotted class path, usually from a
``register()`` function it declares as an entry point in the port's group:

==================  ========================  ==========================
Instance            Entry-point group         Port base class
==================  ========================  ==========================
``providers``       ``protean.providers``     ``BaseProvider``
``brokers``         ``protean.brokers``       ``BaseBroker``
``event_stores``    ``protean.event_stores``  ``BaseEventStore``
``caches``          ``protean.caches``        ``BaseCache``
==================  ========================  ==========================
"""

import logging
from collections.abc import Callable
from importlib import import_module, metadata
from typing import TYPE_CHECKING, Generic, TypeVar, cast

from protean.exceptions import ConfigurationError

if TYPE_CHECKING:
    # Runtime imports would cycle: the adapter modules import this one.
    from protean.port.broker import BaseBroker
    from protean.port.cache import BaseCache
    from protean.port.event_store import BaseEventStore
    from protean.port.provider import BaseProvider

logger = logging.getLogger(__name__)

PortT = TypeVar("PortT")


class AdapterRegistry(Generic[PortT]):
    """Registry of the adapter classes that implement one port.

    Registration stores a dotted class path and imports nothing, so an adapter
    whose optional dependencies are missing costs nothing until it is used.
    The first ``get()`` call loads every entry point in ``group``; later calls
    do not look again, and ``clear()`` does not reset that.

    Args:
        group: The entry-point group whose ``register()`` functions are loaded.
        port_name: The port's display name, used in error messages.
        after_load: Called with the name and class after each successful
            ``get()``, for checks that apply to one port only.
    """

    def __init__(
        self,
        group: str,
        port_name: str,
        after_load: Callable[[str, type[PortT]], None] | None = None,
    ) -> None:
        self.group = group
        self.port_name = port_name
        self.after_load = after_load
        self._paths: dict[str, str] = {}
        self._discovered = False

    def _discover_plugins(self) -> None:
        """Call the ``register()`` function of each entry point in the group once."""
        if self._discovered:
            return

        for entry_point in metadata.entry_points().select(group=self.group):
            try:
                register_func = entry_point.load()
                register_func()
                logger.debug(f"Loaded {self.port_name} plugin: {entry_point.name}")
            except ImportError as e:
                # Usually a missing optional extra, which is a normal install.
                logger.debug(
                    f"Skipping {self.port_name} plugin '{entry_point.name}': {e}"
                )
            except Exception as e:  # noqa: BLE001 - a plugin is third-party code
                logger.warning(
                    f"Failed to load {self.port_name} plugin '{entry_point.name}': {e}"
                )

        self._discovered = True

    def register(self, name: str, class_path: str) -> None:
        """Map ``name`` to the dotted path of an adapter class.

        Logs a warning when ``name`` is already registered, then overwrites it.
        """
        if name in self._paths:
            logger.warning(
                f"{self.port_name.capitalize()} '{name}' is already registered, "
                f"overwriting."
            )

        self._paths[name] = class_path
        logger.debug(f"Registered {self.port_name} '{name}' -> {class_path}")

    def get(self, name: str) -> type[PortT]:
        """Import and return the adapter class registered under ``name``.

        Raises:
            ConfigurationError: When ``name`` is not registered, the class cannot
                be imported, or the class leaves abstract members unimplemented.
        """
        self._discover_plugins()

        if name not in self._paths:
            available = ", ".join(sorted(self._paths)) if self._paths else "none"
            raise ConfigurationError(
                f"Unknown {self.port_name} '{name}'. Available: {available}. "
                f"Ensure the package that provides it is installed."
            )

        class_path = self._paths[name]
        try:
            module_path, class_name = class_path.rsplit(".", maxsplit=1)
            adapter_cls = cast(
                "type[PortT]", getattr(import_module(module_path), class_name)
            )
        except (ImportError, AttributeError, ValueError) as e:
            raise ConfigurationError(
                f"Failed to load {self.port_name} '{name}' from '{class_path}': {e}. "
                f"Ensure the required dependencies are installed."
            ) from e

        missing = sorted(getattr(adapter_cls, "__abstractmethods__", frozenset()))
        if missing:
            raise ConfigurationError(
                f"{self.port_name.capitalize()} '{name}' ({class_path}) does not "
                f"implement: {', '.join(missing)}."
            )

        if self.after_load is not None:
            self.after_load(name, adapter_cls)

        return adapter_cls

    def list(self) -> dict[str, str]:
        """Return a copy of the registered names and their class paths."""
        return self._paths.copy()

    def clear(self) -> None:
        """Remove every registered name."""
        self._paths.clear()


def _warn_missing_lookups(name: str, provider_cls: type["BaseProvider"]) -> None:
    missing = provider_cls.validate_lookups()
    if missing:
        logger.warning(
            f"Provider '{name}' ({provider_cls.__name__}) is missing "
            f"required lookups: {', '.join(missing)}. "
            f"Filters using these lookups will raise NotImplementedError."
        )


providers: AdapterRegistry["BaseProvider"] = AdapterRegistry(
    "protean.providers", "database provider", after_load=_warn_missing_lookups
)
brokers: AdapterRegistry["BaseBroker"] = AdapterRegistry("protean.brokers", "broker")
event_stores: AdapterRegistry["BaseEventStore"] = AdapterRegistry(
    "protean.event_stores", "event store"
)
caches: AdapterRegistry["BaseCache"] = AdapterRegistry("protean.caches", "cache")
