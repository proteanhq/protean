"""Event Upcaster module for schema evolution.

Upcasters transform raw event data from an old schema version to a newer one,
allowing stored events to be deserialized even after the event class evolves.

Example::

    @domain.upcaster(event_type=OrderPlaced, from_version="v1", to_version="v2")
    class UpcastOrderPlacedV1ToV2(BaseUpcaster):
        def upcast(self, data: dict) -> dict:
            data["currency"] = "USD"
            return data
"""

import logging
from abc import abstractmethod
from typing import Any, TypeVar

from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.utils.container import Element, OptionsMixin

logger = logging.getLogger(__name__)


class BaseUpcaster(Element, OptionsMixin):
    """Base class for event upcasters.

    Subclasses must implement :meth:`upcast` which receives the raw event
    payload dict (as stored in the event store) and returns a transformed
    dict compatible with the target version's schema.

    Meta Options:
        event_type: The event class this upcaster targets (current version).
        from_version: Source version string (e.g. ``"v1"``).
        to_version: Target version string (e.g. ``"v2"``).
    """

    def __new__(cls, *args: Any, **kwargs: Any) -> "BaseUpcaster":
        if cls is BaseUpcaster:
            raise NotSupportedError("BaseUpcaster cannot be instantiated")
        return super().__new__(cls)

    @classmethod
    def _default_options(cls) -> list[tuple[str, Any]]:
        return [
            ("event_type", None),
            ("from_version", None),
            ("to_version", None),
        ]

    @abstractmethod
    def upcast(self, data: dict) -> dict:
        """Transform event data from ``from_version`` to ``to_version``.

        Args:
            data: The raw event payload dictionary as stored.

        Returns:
            The transformed payload dictionary compatible with ``to_version``.
        """
        ...


_T = TypeVar("_T")


def upcaster_factory(element_cls: type[_T], domain: Any, **opts: Any) -> type[_T]:
    """Validate and derive an upcaster class from *element_cls*."""
    from protean.core.event import BaseEvent
    from protean.utils import derive_element_class

    element_cls = derive_element_class(element_cls, BaseUpcaster, **opts)

    # --- Validate required options ---
    if not element_cls.meta_.event_type:
        raise IncorrectUsageError(
            f"Upcaster `{element_cls.__name__}` must specify `event_type`"
        )

    if not element_cls.meta_.from_version:
        raise IncorrectUsageError(
            f"Upcaster `{element_cls.__name__}` must specify `from_version`"
        )

    if not element_cls.meta_.to_version:
        raise IncorrectUsageError(
            f"Upcaster `{element_cls.__name__}` must specify `to_version`"
        )

    # event_type must be a BaseEvent subclass (or a string for lazy resolution)
    event_type = element_cls.meta_.event_type
    if not isinstance(event_type, str) and not (
        isinstance(event_type, type) and issubclass(event_type, BaseEvent)
    ):
        raise IncorrectUsageError(
            f"Upcaster `{element_cls.__name__}` event_type must be an Event class, "
            f"got `{event_type}`"
        )

    # from_version and to_version must differ
    if element_cls.meta_.from_version == element_cls.meta_.to_version:
        raise IncorrectUsageError(
            f"Upcaster `{element_cls.__name__}`: "
            f"from_version and to_version must differ"
        )

    return element_cls
