"""Tests for AdapterRegistry and its four instances in protean.infra.registry."""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from importlib import import_module, metadata
from importlib.metadata import EntryPoint, EntryPoints
from typing import Any
from unittest.mock import patch

import pytest

from protean import Domain
from protean.adapters.broker.inline import InlineBroker
from protean.adapters.cache.memory import MemoryCache
from protean.adapters.event_store.memory import MemoryEventStore
from protean.adapters.repository.memory import MemoryProvider
from protean.exceptions import ConfigurationError
from protean.infra.registry import (
    AdapterRegistry,
    brokers,
    caches,
    event_stores,
    providers,
)
from protean.port.broker import BaseBroker
from protean.port.cache import CachePort
from protean.port.event_store import BaseEventStore
from protean.port.provider import BaseProvider
from tests.infra.adapters import (
    CustomBroker,
    CustomCache,
    CustomEventStore,
    CustomProvider,
)
from tests.shared import module_unavailable

LOGGER = "protean.infra.registry"


@dataclass(frozen=True)
class Port:
    registry: AdapterRegistry[Any]
    group: str
    port_name: str
    base: type
    complete_cls: type
    custom_cls: type
    # Builds the domain config that selects ``name`` for this port.
    config: Callable[[str], dict[str, Any]]
    # Returns the adapter instance the domain built for this port.
    built: Callable[[Domain], object]


PORTS = [
    Port(
        providers,
        "protean.providers",
        "database provider",
        BaseProvider,
        MemoryProvider,
        CustomProvider,
        lambda name: {"databases": {"default": {"provider": name}}},
        lambda domain: domain.providers["default"],
    ),
    Port(
        brokers,
        "protean.brokers",
        "broker",
        BaseBroker,
        InlineBroker,
        CustomBroker,
        lambda name: {"brokers": {"default": {"provider": name}}},
        lambda domain: domain.brokers["default"],
    ),
    Port(
        event_stores,
        "protean.event_stores",
        "event store",
        BaseEventStore,
        MemoryEventStore,
        CustomEventStore,
        lambda name: {"event_store": {"provider": name}},
        lambda domain: domain.event_store.store,
    ),
    Port(
        caches,
        "protean.caches",
        "cache",
        CachePort,
        MemoryCache,
        CustomCache,
        lambda name: {"caches": {"default": {"provider": name}}},
        lambda domain: domain.caches["default"]._adapter,
    ),
]
PORT_IDS = [port.group.removeprefix("protean.") for port in PORTS]


def _path(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _entry_points(*specs: tuple[str, str, str]) -> EntryPoints:
    """Build real entry points from ``(name, "module:attr", group)`` triples."""
    return EntryPoints(
        EntryPoint(name=name, value=value, group=group) for name, value, group in specs
    )


def _register_custom(port: Port) -> str:
    """The entry-point value of the helper that registers ``port.custom_cls``."""
    snake = port.group.removeprefix("protean.").removesuffix("s")
    return f"tests.infra.adapters:register_custom_{snake}"


def _records_naming(caplog, plugin_name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if f"'{plugin_name}'" in r.getMessage()]


@pytest.fixture(autouse=True)
def restore_registries() -> Iterator[None]:
    """Put back every instance's registered names and discovery flag."""
    saved = [(reg, reg.list(), reg._discovered) for reg in (p.registry for p in PORTS)]
    yield
    for reg, paths, discovered in saved:
        reg.clear()
        for name, path in paths.items():
            reg._paths[name] = path
        reg._discovered = discovered


@pytest.fixture(params=PORTS, ids=PORT_IDS)
def port(request) -> Port:
    return request.param


@pytest.fixture
def empty(port: Port) -> AdapterRegistry[Any]:
    """The port's registry with no names and entry-point discovery already done."""
    port.registry.clear()
    port.registry._discovered = True
    return port.registry


@pytest.mark.no_test_domain
class TestRegistration:
    def test_register_then_get_returns_the_class(self, port, empty):
        empty.register("custom", _path(port.complete_cls))

        assert empty.get("custom") is port.complete_cls

    def test_register_overwrites_and_warns(self, port, empty, caplog):
        caplog.set_level(logging.WARNING, logger=LOGGER)
        empty.register("custom", "path.to.First")
        empty.register("custom", _path(port.complete_cls))

        assert empty.list() == {"custom": _path(port.complete_cls)}
        records = _records_naming(caplog, "custom")
        assert [r.levelno for r in records] == [logging.WARNING]
        assert records[0].getMessage() == (
            f"{port.port_name.capitalize()} 'custom' is already registered, "
            f"overwriting."
        )

    def test_register_does_not_import(self, empty):
        empty.register("custom", "no.such.module.Adapter")

        assert empty.list() == {"custom": "no.such.module.Adapter"}

    def test_list_returns_a_copy(self, empty):
        empty.register("one", "path.to.One")

        listed = empty.list()
        listed["two"] = "path.to.Two"

        assert empty.list() == {"one": "path.to.One"}

    def test_list_does_not_trigger_discovery(self, empty):
        empty._discovered = False
        with patch("importlib.metadata.entry_points") as entry_points:
            empty.list()

        entry_points.assert_not_called()
        assert empty._discovered is False

    def test_clear_removes_every_name(self, empty):
        empty.register("one", "path.to.One")
        empty.register("two", "path.to.Two")

        empty.clear()

        assert empty.list() == {}

    def test_instances_carry_their_group_and_port_name(self, port):
        assert port.registry.group == port.group
        assert port.registry.port_name == port.port_name


@pytest.mark.no_test_domain
class TestUnknownName:
    def test_lists_registered_names_sorted(self, port, empty):
        empty.register("zeta", "path.to.Zeta")
        empty.register("alpha", "path.to.Alpha")

        with pytest.raises(ConfigurationError) as exc_info:
            empty.get("nope")

        assert str(exc_info.value) == (
            f"Unknown {port.port_name} 'nope'. Available: alpha, zeta. "
            f"Ensure the package that provides it is installed."
        )

    def test_says_none_when_nothing_is_registered(self, port, empty):
        with pytest.raises(ConfigurationError) as exc_info:
            empty.get("nope")

        assert f"Unknown {port.port_name} 'nope'. Available: none." in str(
            exc_info.value
        )

    def test_none_as_name(self, port, empty):
        with pytest.raises(ConfigurationError) as exc_info:
            empty.get(None)

        assert f"Unknown {port.port_name} 'None'" in str(exc_info.value)


@pytest.mark.no_test_domain
class TestImportFailure:
    def test_missing_module(self, port, empty):
        empty.register("bad", "no.such.module.Adapter")

        with pytest.raises(ConfigurationError) as exc_info:
            empty.get("bad")

        message = str(exc_info.value)
        assert (
            f"Failed to load {port.port_name} 'bad' from 'no.such.module.Adapter'"
            in message
        )
        assert "No module named 'no'" in message
        assert "Ensure the required dependencies are installed" in message

    def test_missing_class_in_module(self, port, empty):
        empty.register("bad", "tests.infra.adapters.NoSuchAdapter")

        with pytest.raises(ConfigurationError) as exc_info:
            empty.get("bad")

        message = str(exc_info.value)
        assert f"Failed to load {port.port_name} 'bad'" in message
        assert "NoSuchAdapter" in message

    @pytest.mark.parametrize("class_path", ["Adapter", ".Adapter", ".rel.Adapter"])
    def test_path_that_is_not_absolute_and_dotted(self, port, empty, class_path):
        empty.register("bad", class_path)

        with pytest.raises(ConfigurationError) as exc_info:
            empty.get("bad")

        assert str(exc_info.value) == (
            f"Failed to load {port.port_name} 'bad' from '{class_path}': expected "
            f"an absolute dotted path of the form 'module.ClassName'."
        )

    def test_value_error_from_the_module_propagates(self, empty, tmp_path, monkeypatch):
        """The module's own failure is not reported as a missing dependency."""
        (tmp_path / "raises_on_import.py").write_text(
            "raise ValueError('bad setting at import')\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        empty.register("bad", "raises_on_import.Adapter")

        with pytest.raises(ValueError, match="bad setting at import"):
            empty.get("bad")


@pytest.mark.no_test_domain
class TestCompleteness:
    def test_incomplete_class_is_rejected_naming_every_missing_member(
        self, port, empty
    ):
        name = port.base.__name__.removeprefix("Base").removesuffix("Port")
        path = f"tests.infra.adapters.Incomplete{name}"
        empty.register("partial", path)

        with pytest.raises(ConfigurationError) as exc_info:
            empty.get("partial")

        message = str(exc_info.value)
        expected_missing = set(port.base.__abstractmethods__)
        assert expected_missing, "the port base must declare abstract members"
        assert message.startswith(
            f"{port.port_name.capitalize()} 'partial' ({path}) does not implement: "
        )
        listed = message.split("does not implement: ", 1)[1].rstrip(".")
        assert set(listed.split(", ")) == expected_missing
        assert listed.split(", ") == sorted(expected_missing)

    def test_complete_class_loads(self, port, empty):
        assert port.complete_cls.__abstractmethods__ == frozenset()
        empty.register("whole", _path(port.complete_cls))

        assert empty.get("whole") is port.complete_cls

    def test_every_builtin_adapter_is_complete(self, port):
        port.registry._discovered = False
        port.registry._discover_plugins()

        registered = port.registry.list()
        assert registered, f"no built-in {port.port_name} was discovered"
        for name in registered:
            assert port.registry.get(name).__abstractmethods__ == frozenset()


@pytest.mark.no_test_domain
class TestAfterLoad:
    def test_provider_with_missing_lookups_warns(self, caplog):
        providers.clear()
        providers._discovered = True
        providers.register("short", "tests.infra.adapters.ProviderMissingLookups")
        caplog.set_level(logging.WARNING, logger=LOGGER)

        providers.get("short")

        records = _records_naming(caplog, "short")
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert records[0].getMessage() == (
            "Provider 'short' (ProviderMissingLookups) is missing required "
            "lookups: made_up. Filters using these lookups will raise "
            "NotImplementedError."
        )

    def test_provider_with_every_lookup_does_not_warn(self, caplog):
        providers.clear()
        providers._discovered = True
        providers.register("full", _path(MemoryProvider))
        caplog.set_level(logging.WARNING, logger=LOGGER)

        providers.get("full")

        assert "missing required lookups" not in caplog.text

    @pytest.mark.parametrize("registry", [brokers, event_stores, caches])
    def test_other_ports_run_no_after_load_check(self, registry):
        assert registry.after_load is None

    def test_after_load_receives_name_and_class(self):
        calls: list[tuple[str, type]] = []
        registry: AdapterRegistry[CachePort] = AdapterRegistry(
            "protean.test", "test", after_load=lambda n, c: calls.append((n, c))
        )
        registry._discovered = True
        registry.register("memory", _path(MemoryCache))

        registry.get("memory")

        assert calls == [("memory", MemoryCache)]

    def test_after_load_does_not_run_for_a_rejected_class(self):
        calls: list[tuple[str, type]] = []
        registry: AdapterRegistry[CachePort] = AdapterRegistry(
            "protean.test", "test", after_load=lambda n, c: calls.append((n, c))
        )
        registry._discovered = True
        registry.register("partial", "tests.infra.adapters.IncompleteCache")

        with pytest.raises(ConfigurationError):
            registry.get("partial")

        assert calls == []


@pytest.mark.no_test_domain
class TestDiscovery:
    def test_get_loads_the_entry_points_of_its_own_group(self, port, empty):
        empty._discovered = False
        eps = _entry_points(
            ("custom", _register_custom(port), port.group),
            ("other", "tests.infra.adapters:register_that_fails", "protean.other"),
        )

        with patch("importlib.metadata.entry_points", return_value=eps):
            assert empty.get("custom") is port.custom_cls

        assert empty.list() == {"custom": _path(port.custom_cls)}

    def test_discovery_runs_once(self, empty):
        empty._discovered = False
        eps = _entry_points()

        with patch("importlib.metadata.entry_points", return_value=eps) as first:
            empty._discover_plugins()
        with patch("importlib.metadata.entry_points", return_value=eps) as second:
            empty._discover_plugins()

        first.assert_called_once()
        second.assert_not_called()
        assert empty._discovered is True

    def test_get_triggers_discovery_on_first_call(self, port, empty):
        empty._discovered = False
        empty.register("whole", _path(port.complete_cls))

        with patch(
            "importlib.metadata.entry_points", return_value=_entry_points()
        ) as entry_points:
            empty.get("whole")

        entry_points.assert_called_once()

    def test_clear_does_not_reset_discovery(self, empty):
        empty.clear()

        assert empty._discovered is True

    def test_missing_module_at_load_is_skipped_quietly(self, port, empty, caplog):
        caplog.set_level(logging.DEBUG, logger=LOGGER)
        empty._discovered = False
        eps = _entry_points(
            ("absent", "tests.infra.no_such_module:register", port.group)
        )

        with patch("importlib.metadata.entry_points", return_value=eps):
            empty._discover_plugins()

        records = _records_naming(caplog, "absent")
        assert len(records) == 1
        assert records[0].levelno == logging.DEBUG
        message = records[0].getMessage()
        assert f"Skipping {port.port_name} plugin 'absent'" in message
        assert "No module named 'tests.infra.no_such_module'" in message

    def test_import_error_from_register_is_skipped_quietly(self, port, empty, caplog):
        caplog.set_level(logging.DEBUG, logger=LOGGER)
        empty._discovered = False
        eps = _entry_points(
            ("lazy", "tests.infra.adapters:register_needing_missing_extra", port.group)
        )

        with patch("importlib.metadata.entry_points", return_value=eps):
            empty._discover_plugins()

        records = _records_naming(caplog, "lazy")
        assert len(records) == 1
        assert records[0].levelno == logging.DEBUG
        assert records[0].getMessage() == (
            f"Skipping {port.port_name} plugin 'lazy': No module named 'redis'"
        )

    def test_failing_register_logs_a_warning(self, port, empty, caplog):
        caplog.set_level(logging.DEBUG, logger=LOGGER)
        empty._discovered = False
        eps = _entry_points(
            ("broken", "tests.infra.adapters:register_that_fails", port.group)
        )

        with patch("importlib.metadata.entry_points", return_value=eps):
            empty._discover_plugins()

        assert empty.list() == {}
        records = _records_naming(caplog, "broken")
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert records[0].getMessage() == (
            f"Failed to load {port.port_name} plugin 'broken': "
            f"Registration function failed"
        )

    def test_missing_register_function_logs_a_warning(self, port, empty, caplog):
        caplog.set_level(logging.DEBUG, logger=LOGGER)
        empty._discovered = False
        eps = _entry_points(
            ("noattr", "tests.infra.adapters:no_such_register", port.group)
        )

        with patch("importlib.metadata.entry_points", return_value=eps):
            empty._discover_plugins()

        records = _records_naming(caplog, "noattr")
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert f"Failed to load {port.port_name} plugin 'noattr'" in (
            records[0].getMessage()
        )

    def test_discovery_continues_past_failures(self, port, empty):
        empty._discovered = False
        eps = _entry_points(
            ("broken", "tests.infra.adapters:register_that_fails", port.group),
            ("absent", "tests.infra.no_such_module:register", port.group),
            ("custom", _register_custom(port), port.group),
        )

        with patch("importlib.metadata.entry_points", return_value=eps):
            empty._discover_plugins()

        assert empty.list() == {"custom": _path(port.custom_cls)}


@pytest.mark.no_test_domain
class TestDomainBuildsTheDiscoveredAdapter:
    """A package's entry point is enough for a domain to build its adapter."""

    def test_domain_builds_the_class_registered_by_an_entry_point(self, port):
        # Load the real plugins first, so the domain finds its other built-in
        # adapters, then let this port discover only the test entry point.
        for other in PORTS:
            other.registry._discover_plugins()
        eps = _entry_points(("custom", _register_custom(port), port.group))
        port.registry._discovered = False
        domain = Domain(name="Plugged", config=port.config("custom"))

        with patch("importlib.metadata.entry_points", return_value=eps):
            domain.init(traverse=False)

        assert type(port.built(domain)) is port.custom_cls


@pytest.mark.no_test_domain
class TestUnknownNameThroughDomainInit:
    def test_unknown_event_store_lists_the_built_in_names(self):
        domain = Domain(name="Unknown", config={"event_store": {"provider": "nope"}})

        with pytest.raises(ConfigurationError) as exc_info:
            domain.init(traverse=False)

        message = str(exc_info.value)
        assert "Unknown event store 'nope'" in message
        assert "memory" in message
        assert "message_db" in message

    def test_unknown_cache_lists_the_built_in_names(self):
        domain = Domain(
            name="Unknown", config={"caches": {"default": {"provider": "nope"}}}
        )

        with pytest.raises(ConfigurationError) as exc_info:
            domain.init(traverse=False)

        message = str(exc_info.value)
        assert "Unknown cache 'nope'" in message
        assert "memory" in message
        assert "redis" in message


@pytest.mark.no_test_domain
class TestBuiltInRegistration:
    """Each built-in register() function maps its name to its class."""

    @pytest.mark.parametrize(
        ("registry", "name", "class_path", "extra"),
        [
            (providers, "memory", "repository.memory.MemoryProvider", None),
            (providers, "postgresql", "repository.sqlalchemy.PostgresqlProvider", "sqlalchemy"),
            (providers, "sqlite", "repository.sqlalchemy.SqliteProvider", "sqlalchemy"),
            (providers, "mysql", "repository.sqlalchemy.MysqlProvider", "sqlalchemy"),
            (providers, "mssql", "repository.sqlalchemy.MssqlProvider", "sqlalchemy"),
            (providers, "elasticsearch", "repository.elasticsearch.ESProvider", "elasticsearch"),
            (brokers, "inline", "broker.inline.InlineBroker", None),
            (brokers, "redis", "broker.redis.RedisBroker", "redis"),
            (brokers, "redis_pubsub", "broker.redis_pubsub.RedisPubSubBroker", "redis"),
            (event_stores, "memory", "event_store.memory.MemoryEventStore", None),
            (event_stores, "message_db", "event_store.message_db.MessageDBStore", "message_db"),
            (caches, "memory", "cache.memory.MemoryCache", None),
            (caches, "redis", "cache.redis.RedisCache", "redis"),
        ],
    )  # fmt: skip
    def test_declared_entry_point_registers_its_class(
        self, registry, name, class_path, extra
    ):
        if extra:
            pytest.importorskip(extra)
        declared = {
            ep.name: ep for ep in metadata.entry_points().select(group=registry.group)
        }
        assert name in declared, f"{registry.group} declares no '{name}' entry point"
        registry.clear()
        registry._discovered = True

        declared[name].load()()

        full_path = f"protean.adapters.{class_path}"
        assert registry.list() == {name: full_path}
        module_path, cls_name = full_path.rsplit(".", maxsplit=1)
        assert registry.get(name) is getattr(import_module(module_path), cls_name)

    def test_mysql_registration_without_sqlalchemy_registers_nothing(self):
        """The provider is optional, so `import protean` works without SQLAlchemy."""
        from protean.adapters.repository.sqlalchemy import register_mysql

        providers.clear()
        with module_unavailable("sqlalchemy"):
            register_mysql()

        assert "mysql" not in providers.list()


@pytest.mark.no_test_domain
class TestMissingOptionalExtra:
    """An adapter whose extra is not installed stays registered by name."""

    @pytest.mark.parametrize(
        ("registry", "name", "dependency", "adapter_module"),
        [
            (event_stores, "message_db", "psycopg2", "protean.adapters.event_store.message_db"),
            (caches, "redis", "redis", "protean.adapters.cache.redis"),
        ],
    )  # fmt: skip
    def test_get_names_the_missing_module(
        self, registry, name, dependency, adapter_module
    ):
        registry.clear()
        registry._discovered = False

        with module_unavailable(dependency, reload=(adapter_module,)):
            registry._discover_plugins()
            assert name in registry.list()

            with pytest.raises(ConfigurationError) as exc_info:
                registry.get(name)

        message = str(exc_info.value)
        assert message.startswith(f"Failed to load {registry.port_name} '{name}'")
        assert dependency in message
        assert "Ensure the required dependencies are installed" in message


@pytest.mark.no_test_domain
class TestRemovedNames:
    """The per-port registry names are gone; `protean.infra.registry` replaces them."""

    @pytest.mark.parametrize(
        ("module", "name"),
        [
            ("protean.port.provider", "registry"),
            ("protean.port.provider", "ProviderRegistry"),
            ("protean.port.broker", "registry"),
            ("protean.port.broker", "BrokerRegistry"),
            ("protean.adapters.repository", "registry"),
            ("protean.adapters.broker", "registry"),
            ("protean.adapters.event_store", "EVENT_STORE_PROVIDERS"),
            ("protean.adapters.cache", "CACHE_PROVIDERS"),
        ],
    )
    def test_name_is_not_defined(self, module, name):
        assert not hasattr(import_module(module), name)
