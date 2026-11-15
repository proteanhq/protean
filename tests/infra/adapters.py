"""Adapter classes and register() functions that the registry tests load by path."""

import functools
from collections.abc import Mapping
from typing import ClassVar

from protean.adapters.broker.inline import InlineBroker
from protean.adapters.cache.memory import MemoryCache
from protean.adapters.event_store.memory import MemoryEventStore
from protean.adapters.repository.memory import MemoryProvider
from protean.infra.registry import brokers, caches, event_stores, providers
from protean.port.broker import BaseBroker
from protean.port.cache import CachePort
from protean.port.dao import REQUIRED_LOOKUPS, LookupPort
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


class ProviderWithoutLookup(MemoryProvider):
    """A memory provider whose ``get_lookups()`` leaves out ``omitted``."""

    omitted: ClassVar[str]

    # Cached like the mixin's ``get_lookups``, because registering a lookup on
    # ``MemoryProvider`` calls ``cache_clear`` on every subclass.
    @classmethod
    @functools.cache
    def get_lookups(cls) -> Mapping[str, type[LookupPort]]:
        lookups = MemoryProvider.get_lookups()
        return {name: lookup for name, lookup in lookups.items() if name != cls.omitted}


# One subclass per required lookup, at module level so the registry can import
# each one by its dotted path.
PROVIDERS_WITHOUT_LOOKUP: dict[str, type[ProviderWithoutLookup]] = {}
for _lookup_name in sorted(REQUIRED_LOOKUPS):
    _provider_cls = type(
        f"ProviderWithout{_lookup_name.capitalize()}",
        (ProviderWithoutLookup,),
        {"omitted": _lookup_name, "__module__": __name__},
    )
    globals()[_provider_cls.__name__] = _provider_cls
    PROVIDERS_WITHOUT_LOOKUP[_lookup_name] = _provider_cls


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
