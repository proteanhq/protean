"""Adapter classes and register() functions that the registry tests load by path."""

from protean.adapters.broker.inline import InlineBroker
from protean.adapters.cache.memory import MemoryCache
from protean.adapters.event_store.memory import MemoryEventStore
from protean.adapters.repository.memory import MemoryProvider
from protean.infra.registry import brokers, caches, event_stores, providers
from protean.port.broker import BaseBroker
from protean.port.cache import CachePort
from protean.port.event_store import BaseEventStore
from protean.port.provider import BaseProvider


class CustomProvider(MemoryProvider):
    pass


class CustomBroker(InlineBroker):
    pass


class CustomEventStore(MemoryEventStore):
    pass


class CustomCache(MemoryCache):
    pass


class IncompleteProvider(BaseProvider):
    pass


class IncompleteBroker(BaseBroker):
    pass


class IncompleteEventStore(BaseEventStore):
    pass


class IncompleteCache(CachePort):
    pass


class ProviderMissingLookups(MemoryProvider):
    REQUIRED_LOOKUPS = MemoryProvider.REQUIRED_LOOKUPS | {"made_up"}


def register_custom_provider() -> None:
    providers.register("custom", "tests.infra.adapters.CustomProvider")


def register_custom_broker() -> None:
    brokers.register("custom", "tests.infra.adapters.CustomBroker")


def register_custom_event_store() -> None:
    event_stores.register("custom", "tests.infra.adapters.CustomEventStore")


def register_custom_cache() -> None:
    caches.register("custom", "tests.infra.adapters.CustomCache")


def register_needing_missing_extra() -> None:
    raise ModuleNotFoundError("No module named 'redis'", name="redis")


def register_that_fails() -> None:
    raise RuntimeError("Registration function failed")
