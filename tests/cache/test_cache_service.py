"""The `Cache` service gates calls on the adapter's declared capabilities.

The stub adapters here are registered by dotted path, so they live at module
level.
"""

from typing import Any

import pytest

from protean import Domain, handle
from protean.adapters.cache.memory import MemoryCache
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.exceptions import ConfigurationError, NotSupportedError
from protean.fields import Identifier, String
from protean.infra.cache import Cache, Caches
from protean.infra.registry import caches as cache_registry
from protean.port.cache import (
    CacheCapabilities,
    CacheEntry,
    CacheHealth,
    CachePatternPort,
    CachePort,
    CacheTTLPort,
)


class Person(BaseProjection):
    key: Identifier(identifier=True)
    name: String(required=True)


class KeyValueCache(CachePort):
    """Implements only `CachePort` and records the TTL each `put` received."""

    def __init__(self, name: str, domain: Any, config: Any) -> None:
        self.name = name
        self.domain = domain
        self.config = config
        self.store: dict[str, CacheEntry] = {}
        self.put_ttls: list[float | None] = []

    @property
    def capabilities(self) -> CacheCapabilities:
        return CacheCapabilities.KEY_VALUE

    def ping(self) -> bool:
        return True

    def health(self) -> CacheHealth:
        return CacheHealth(pool=None)

    def get_connection(self) -> object:
        return self.store

    def clear(self) -> None:
        self.store.clear()

    def get(self, key: str) -> CacheEntry | None:
        return self.store.get(key)

    def put(self, key: str, value: CacheEntry, ttl: float | None) -> None:
        self.store[key] = value
        self.put_ttls.append(ttl)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


class TTLWithoutGetTTL(KeyValueCache):
    """Declares `TTL` and has `set_ttl`, but not `get_ttl`."""

    @property
    def capabilities(self) -> CacheCapabilities:
        return CacheCapabilities.KEY_VALUE | CacheCapabilities.TTL

    def set_ttl(self, key: str, ttl: float) -> None:
        pass


class PatternWithoutKeysMatching(KeyValueCache):
    """Declares `PATTERN_MATCH` and has two of its three members."""

    @property
    def capabilities(self) -> CacheCapabilities:
        return CacheCapabilities.KEY_VALUE | CacheCapabilities.PATTERN_MATCH

    def count_matching(self, pattern: str) -> int:
        return 0

    def delete_matching(self, pattern: str) -> None:
        pass


class ExpiringPatternCache(KeyValueCache, CachePatternPort):
    """Lists every stored key, but reads keys in `expired` back as `None`."""

    def __init__(self, name: str, domain: Any, config: Any) -> None:
        super().__init__(name, domain, config)
        self.expired: set[str] = set()

    @property
    def capabilities(self) -> CacheCapabilities:
        return CacheCapabilities.KEY_VALUE | CacheCapabilities.PATTERN_MATCH

    def get(self, key: str) -> CacheEntry | None:
        return None if key in self.expired else self.store.get(key)

    def keys_matching(self, pattern: str) -> list[str]:
        return sorted(self.store)

    def count_matching(self, pattern: str) -> int:
        return len(self.store)

    def delete_matching(self, pattern: str) -> None:
        self.store.clear()


class DuckTypedTTL(KeyValueCache):
    """Declares `TTL` and has both TTL members, but does not subclass
    `CacheTTLPort`."""

    @property
    def capabilities(self) -> CacheCapabilities:
        return CacheCapabilities.KEY_VALUE | CacheCapabilities.TTL

    def set_ttl(self, key: str, ttl: float) -> None:
        pass

    def get_ttl(self, key: str) -> float | None:
        return None


class AdapterWithoutCapabilities:
    """The shape of an adapter written for the earlier cache base class."""

    def __init__(self, name: str, domain: Any, conn_info: Any) -> None:
        self.name = name
        self.domain = domain
        self.conn_info = conn_info


class AdapterWithoutConfig(AdapterWithoutCapabilities):
    @property
    def capabilities(self) -> CacheCapabilities:
        return CacheCapabilities.KEY_VALUE


class UndeclaredTTL(KeyValueCache, CacheTTLPort):
    """Implements `CacheTTLPort` without declaring `TTL`."""

    def set_ttl(self, key: str, ttl: float) -> None:
        raise AssertionError("The service must not call an undeclared member")

    def get_ttl(self, key: str) -> float | None:
        raise AssertionError("The service must not call an undeclared member")


def _key_value_cache() -> Cache:
    cache = Cache(KeyValueCache("plain", None, {"provider": "plain"}))
    cache._register_projection(Person)
    return cache


class TestAKeyValueOnlyCache:
    @pytest.mark.parametrize(
        ("call", "flag"),
        [
            (lambda c: c._get_all("person:::*"), "PATTERN_MATCH"),
            (lambda c: c.count("person:::*"), "PATTERN_MATCH"),
            (lambda c: c.remove_by_key_pattern("person:::*"), "PATTERN_MATCH"),
            (lambda c: c.set_ttl("person:::1", 60), "TTL"),
            (lambda c: c.get_ttl("person:::1"), "TTL"),
        ],
    )
    def test_a_gated_method_names_the_cache_and_the_flag(self, call, flag):
        with pytest.raises(NotSupportedError) as exc:
            call(_key_value_cache())

        assert "Cache 'plain'" in str(exc.value)
        assert f"CacheCapabilities.{flag}" in str(exc.value)

    def test_the_key_value_methods_work(self):
        cache = _key_value_cache()
        person = Person(key="1", name="Ada")
        other = Person(key="2", name="Grace")

        cache.add(person)
        cache.add(other)
        assert cache.get("person:::1") == person

        cache.remove(person)
        assert cache.get("person:::1") is None

        cache.remove_by_key("person:::2")
        assert cache.get("person:::2") is None

        cache.add(person)
        cache.clear()
        assert cache._adapter.store == {}

    def test_an_unset_ttl_stores_the_entry_without_expiry(self):
        cache = _key_value_cache()

        cache.add(Person(key="1", name="Ada"))

        assert cache._adapter.put_ttls == [None]

    def test_an_explicit_ttl_is_not_supported(self):
        cache = _key_value_cache()

        with pytest.raises(NotSupportedError) as exc:
            cache.add(Person(key="1", name="Ada"), ttl=60)

        assert "Cache 'plain'" in str(exc.value)
        assert "CacheCapabilities.TTL" in str(exc.value)
        assert cache._adapter.store == {}

    def test_a_bad_ttl_is_rejected_before_the_capability_check(self):
        cache = _key_value_cache()

        with pytest.raises(ConfigurationError, match="positive number of seconds"):
            cache.add(Person(key="1", name="Ada"), ttl=0)

        assert cache._adapter.store == {}

    def test_capabilities_are_the_adapters(self):
        assert _key_value_cache().capabilities == CacheCapabilities.KEY_VALUE


class TestReads:
    def test_get_names_an_unregistered_projection(self):
        cache = _key_value_cache()

        with pytest.raises(KeyError) as exc:
            cache.get("order:::1")

        assert "order" in str(exc.value)

    def test_get_all_skips_an_entry_that_expires_after_the_scan(self):
        cache = Cache(ExpiringPatternCache("scan", None, {"provider": "scan"}))
        cache._register_projection(Person)
        cache.add(Person(key="1", name="Ada"))
        cache.add(Person(key="2", name="Grace"))
        cache._adapter.expired.add("person:::1")

        entries = cache._get_all("person:::*")

        assert [str(p.key) for p in entries] == ["2"]

    @pytest.mark.parametrize(
        ("pattern", "prefix"), [("order:::*", "order"), ("*", "*")]
    )
    def test_get_all_names_a_pattern_without_a_registered_prefix(self, pattern, prefix):
        cache = Cache(ExpiringPatternCache("scan", None, {"provider": "scan"}))
        cache._register_projection(Person)
        cache.add(Person(key="1", name="Ada"))

        with pytest.raises(KeyError) as exc:
            cache._get_all(pattern)

        message = str(exc.value)
        assert f"under {prefix!r}" in message
        assert "Cache 'scan'" in message
        assert "`pattern_for`" in message


class TestADuckTypedAdapter:
    def test_is_rejected_without_a_claim_that_members_are_missing(self):
        with pytest.raises(ConfigurationError) as exc:
            Cache(DuckTypedTTL("duck", None, {"provider": "duck"}))

        message = str(exc.value)
        assert message == (
            "Cache 'duck' declares CacheCapabilities.TTL, but DuckTypedTTL does "
            "not subclass CacheTTLPort."
        )


class TestAnAdapterForTheEarlierBaseClass:
    @pytest.mark.parametrize(
        ("cls", "attribute"),
        [
            (AdapterWithoutCapabilities, "capabilities"),
            (AdapterWithoutConfig, "config"),
        ],
    )
    def test_is_rejected_naming_the_cache_and_the_attribute(self, cls, attribute):
        with pytest.raises(ConfigurationError) as exc:
            Cache(cls("legacy", None, {"provider": "legacy"}))

        message = str(exc.value)
        assert "Cache 'legacy'" in message
        assert f"no `{attribute}` attribute" in message
        assert "CachePort" in message


class TestTheCapabilityCheckIsOneWay:
    def test_an_undeclared_sub_protocol_is_accepted_and_stays_gated(self):
        cache = Cache(UndeclaredTTL("extra", None, {"provider": "extra"}))

        with pytest.raises(NotSupportedError):
            cache.get_ttl("person:::1")


@pytest.mark.no_test_domain
class TestADeclaredCapabilityNeedsItsSubProtocol:
    @pytest.fixture
    def registered(self):
        names = []

        def register(name: str, cls: type) -> None:
            cache_registry.register(name, f"{cls.__module__}.{cls.__qualname__}")
            names.append(name)

        yield register
        for name in names:
            cache_registry._paths.pop(name, None)

    @pytest.mark.parametrize(
        ("cls", "flag", "port", "member", "present"),
        [
            (TTLWithoutGetTTL, "TTL", "CacheTTLPort", "get_ttl", ["set_ttl"]),
            (
                PatternWithoutKeysMatching,
                "PATTERN_MATCH",
                "CachePatternPort",
                "keys_matching",
                ["count_matching", "delete_matching"],
            ),
        ],
    )
    def test_domain_init_names_the_cache_the_flag_and_the_member(
        self, registered, cls, flag, port, member, present
    ):
        registered("stub", cls)
        domain = Domain(name="Test")
        domain.config["caches"]["default"] = {"provider": "stub"}

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        message = str(exc.value)
        assert "Cache 'default'" in message
        assert f"CacheCapabilities.{flag}" in message
        assert port in message
        assert message.endswith(f"It does not implement: {member}.")
        for name in present:
            assert name not in message


class ClosingKeyValueCache(KeyValueCache):
    """Records which adapters were closed."""

    closed: list[str] = []

    def close(self) -> None:
        ClosingKeyValueCache.closed.append(self.name)


class ClosingTTLWithoutGetTTL(TTLWithoutGetTTL):
    def close(self) -> None:
        ClosingKeyValueCache.closed.append(self.name)


@pytest.mark.no_test_domain
class TestAFailedCapabilityCheckClosesTheAdapters:
    @pytest.fixture(autouse=True)
    def registered(self):
        ClosingKeyValueCache.closed = []
        for name, cls in (
            ("closing", ClosingKeyValueCache),
            ("closing_invalid", ClosingTTLWithoutGetTTL),
        ):
            cache_registry.register(name, f"{cls.__module__}.{cls.__qualname__}")
        yield
        for name in ("closing", "closing_invalid"):
            cache_registry._paths.pop(name, None)

    def test_the_failed_adapter_and_the_caches_built_before_it_are_closed(self):
        domain = Domain(name="Test")
        domain.config["caches"] = {
            "default": {"provider": "closing"},
            "broken": {"provider": "closing_invalid"},
        }

        with pytest.raises(ConfigurationError, match="Cache 'broken'"):
            domain.init(traverse=False)

        assert sorted(ClosingKeyValueCache.closed) == ["broken", "default"]


@pytest.mark.no_test_domain
class TestTheContainerBuildsTheAdapter:
    def test_the_adapter_gets_the_domain_and_an_unmodified_config(self):
        domain = Domain(name="Test")
        domain.config["caches"]["default"] = {"provider": "memory", "TTL": 60}
        domain.init(traverse=False)

        cache = domain.caches["default"]
        assert isinstance(cache._adapter, MemoryCache)
        assert cache._adapter.domain is domain
        assert dict(cache._adapter.config) == {"provider": "memory", "TTL": 60}
        assert "cache" not in domain.config["caches"]["default"]
        assert cache.capabilities == CacheCapabilities.LOCAL
        assert cache.name == "default"


@pytest.mark.no_test_domain
class TestTheContainerBuildsCachesOnFirstUse:
    @pytest.fixture
    def caches(self):
        domain = Domain(name="Test")
        domain.config["caches"] = {"default": {"provider": "memory"}}
        return Caches(domain)

    def test_get_connection_builds_the_caches(self, caches):
        assert caches.get_connection() is caches["default"]._adapter._db._values

    def test_get_connection_names_an_unknown_cache(self, caches):
        with pytest.raises(AssertionError, match="No Provider registered with name"):
            caches.get_connection("missing")

    def test_cache_for_builds_the_caches_and_registers_the_projection(self, caches):
        cache = caches.cache_for(Person)

        assert cache is caches["default"]
        assert "person" in cache._projections

    def test_a_config_without_a_default_cache_is_rejected(self):
        domain = Domain(name="Test")
        domain.config["caches"] = {"other": {"provider": "memory"}}

        with pytest.raises(ConfigurationError, match="'default' provider"):
            Caches(domain)._initialize()


class Signup(BaseAggregate):
    email: String()


class SignedUp(BaseEvent):
    signup_id: Identifier(identifier=True)


class SignupView(BaseProjection):
    signup_id: Identifier(identifier=True)


class SignupViewProjector(BaseProjector):
    @handle(SignedUp)
    def on_signed_up(self, event: SignedUp) -> None:
        pass


@pytest.mark.no_test_domain
class TestAProjectionOnAKeyValueOnlyCache:
    @pytest.fixture
    def domain(self):
        cache_registry.register("plain", f"{__name__}.KeyValueCache")
        domain = Domain(name="Test")
        domain.config["caches"]["default"] = {"provider": "plain"}
        domain.register(Signup)
        domain.register(SignedUp, part_of=Signup)
        domain.register(SignupView, cache="default")
        domain.register(
            SignupViewProjector, projector_for=SignupView, aggregates=[Signup]
        )
        domain.init(traverse=False)
        with domain.domain_context():
            yield domain
        cache_registry._paths.pop("plain", None)

    def test_a_rebuild_raises_before_it_changes_the_cache(self, domain):
        cache = domain.cache_for(SignupView)
        cache.add(SignupView(signup_id="1"))

        with pytest.raises(NotSupportedError, match="PATTERN_MATCH"):
            domain.rebuild_projection(SignupView)

        assert cache._adapter.store == {"signup_view:::1": {"signup_id": "1"}}
        assert cache._adapter.put_ttls == [None]

    def test_counting_the_view_raises(self, domain):
        with pytest.raises(NotSupportedError, match="PATTERN_MATCH"):
            domain.view_for(SignupView).count()
