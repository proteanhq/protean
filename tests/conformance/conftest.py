"""The conformance plugin: run each port's suite against one adapter.

Each port's suite lives in its own folder, ``tests/conformance/<port>/``. A test
there runs against the adapter of that folder's port, ``memory`` by default and
``inline`` for brokers, so a plain ``pytest tests/conformance`` or
``protean test`` run needs no options.

Options
-------
``--port``
    One of ``database``, ``broker``, ``cache`` or ``event_store``. Tests under
    ``tests/conformance/`` outside that port's folder are deselected.
``--adapter``
    The adapter's registered name, such as ``postgresql`` or ``redis``. A name
    the port's registry does not know raises ``ConfigurationError``.
``--adapter-config``
    A JSON object merged over the adapter's built-in configuration.
``--capability``
    A flag name, such as ``EXPECTED_VERSION``. Only tests whose ``requires`` or
    ``requires_any`` marker names that flag are kept. ``none`` keeps only tests
    with neither marker.

Markers
-------
``@pytest.mark.requires(Flag.A, ...)`` skips the test unless the adapter
declares every flag given. ``@pytest.mark.requires_any(Flag.A, Flag.B)`` skips
it unless the adapter declares at least one of them. The skip reason is
``<adapter> does not declare <FLAG>``, or ``<adapter> declares no capabilities``
for an adapter without a ``capabilities`` member, where ``<adapter>`` is the
registered name.

The ``--port`` and ``--capability`` filters leave tests outside
``tests/conformance/`` untouched.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Iterator
from enum import Flag
from pathlib import Path
from typing import Any

import pytest

from protean.domain import Domain
from protean.infra.registry import (
    AdapterRegistry,
    brokers,
    caches,
    event_stores,
    providers,
)
from tests.conformance.flag_coverage import named_flags
from tests.shared import (
    ELASTICSEARCH_URI,
    MESSAGE_DB_URI,
    MSSQL_URI,
    MYSQL_URI,
    POSTGRES_URI,
    REDIS_URI,
)

CONFORMANCE_DIR = Path(__file__).parent

PORTS = ("database", "broker", "cache", "event_store")

DEFAULT_ADAPTERS = {
    "database": "memory",
    "broker": "inline",
    "cache": "memory",
    "event_store": "memory",
}

REGISTRIES: dict[str, AdapterRegistry[Any]] = {
    "database": providers,
    "broker": brokers,
    "cache": caches,
    "event_store": event_stores,
}

# A working configuration for each built-in adapter in this repository's
# Docker services, keyed by port and registered name.
BUILTIN_ADAPTER_CONFIGS: dict[tuple[str, str], dict[str, Any]] = {
    ("database", "memory"): {"provider": "memory"},
    ("database", "postgresql"): {
        "provider": "postgresql",
        "database_uri": POSTGRES_URI,
        "pool_size": 1,
        "max_overflow": 2,
    },
    ("database", "elasticsearch"): {
        "provider": "elasticsearch",
        "database": "elasticsearch",
        "database_uri": ELASTICSEARCH_URI,
    },
    ("database", "sqlite"): {
        "provider": "sqlite",
        "database_uri": "sqlite:///test.db",
    },
    ("database", "mssql"): {
        "provider": "mssql",
        "database_uri": MSSQL_URI,
        "pool_size": 1,
        "max_overflow": 2,
    },
    ("database", "mysql"): {
        "provider": "mysql",
        "database_uri": MYSQL_URI,
        "pool_size": 1,
        "max_overflow": 2,
    },
    ("broker", "inline"): {"provider": "inline"},
    # Redis database numbers differ from the other Redis-backed suites, so this
    # run does not read keys another suite left behind.
    ("broker", "redis"): {"provider": "redis", "URI": f"{REDIS_URI}/8", "TTL": 300},
    ("broker", "redis_pubsub"): {
        "provider": "redis_pubsub",
        "URI": f"{REDIS_URI}/11",
        "TTL": 300,
    },
    ("cache", "memory"): {"provider": "memory", "TTL": 300},
    ("cache", "redis"): {"provider": "redis", "URI": f"{REDIS_URI}/15", "TTL": 300},
    ("event_store", "memory"): {"provider": "memory"},
    ("event_store", "message_db"): {
        "provider": "message_db",
        "database_uri": MESSAGE_DB_URI,
    },
}


def _configure_database(domain: Domain, config: dict[str, Any]) -> None:
    domain.config["databases"]["default"] = config


def _configure_broker(domain: Domain, config: dict[str, Any]) -> None:
    domain.config["brokers"]["default"] = config


def _configure_cache(domain: Domain, config: dict[str, Any]) -> None:
    domain.config["caches"]["default"] = config


def _configure_event_store(domain: Domain, config: dict[str, Any]) -> None:
    domain.config["event_store"] = config


CONFIGURE: dict[str, Callable[[Domain, dict[str, Any]], None]] = {
    "database": _configure_database,
    "broker": _configure_broker,
    "cache": _configure_cache,
    "event_store": _configure_event_store,
}

ADAPTER_OF: dict[str, Callable[[Domain], Any]] = {
    "database": lambda domain: domain.providers["default"],
    "broker": lambda domain: domain.brokers["default"],
    "cache": lambda domain: domain.caches["default"]._adapter,
    "event_store": lambda domain: domain.event_store.store,
}


RESET: dict[str, Callable[[Any], None]] = {
    "database": lambda provider: provider._data_reset(),
    "broker": lambda broker: broker._data_reset(),
    "cache": lambda cache: cache.clear(),
    "event_store": lambda store: store._data_reset(),
}


def reset_and_close(port: str, adapter: Any) -> None:
    """Clear the data ``adapter`` holds, then close it."""
    try:
        RESET[port](adapter)
    finally:
        # Close even when the reset fails, so a run does not leak connections.
        adapter.close()


# ===================================================================
# Hooks
# ===================================================================


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("conformance", "Protean port conformance suites")
    group.addoption(
        "--port",
        choices=PORTS,
        default=None,
        help="Run only this port's conformance suite.",
    )
    group.addoption(
        "--adapter",
        default=None,
        help="Registered adapter name (default: memory, inline for brokers).",
    )
    group.addoption(
        "--adapter-config",
        default=None,
        help="JSON object merged over the adapter's built-in configuration.",
    )
    group.addoption(
        "--capability",
        default=None,
        help="Keep only tests gated on this flag name; 'none' keeps ungated tests.",
    )


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "requires(*flags): skip unless the adapter declares every flag given",
    )
    config.addinivalue_line(
        "markers",
        "requires_any(*flags): skip unless the adapter declares one of the flags",
    )
    # Fail before collection on a malformed value, not once per test.
    parse_adapter_config(config.getoption("adapter_config", default=None))


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    port = config.getoption("port", default=None)
    capability = config.getoption("capability", default=None)
    if port is None and capability is None:
        return

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        (selected if _keeps(item, port, capability) else deselected).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def _keeps(item: pytest.Item, port: str | None, capability: str | None) -> bool:
    """Whether the ``--port`` and ``--capability`` filters keep ``item``."""
    if not item.path.is_relative_to(CONFORMANCE_DIR):
        return True
    if port is not None and port_of(item.path) != port:
        return False
    if capability is None:
        return True

    names = {flag.name for flag in named_flags(item)}
    if capability == "none":
        return not names
    return capability in names


# ===================================================================
# Resolution
# ===================================================================


def port_of(path: Path) -> str | None:
    """Return the port whose folder under ``tests/conformance/`` holds ``path``."""
    if not path.is_relative_to(CONFORMANCE_DIR):
        return None
    parts = path.relative_to(CONFORMANCE_DIR).parts
    if len(parts) > 1 and parts[0] in PORTS:
        return parts[0]
    return None


def parse_adapter_config(raw: str | None) -> dict[str, Any]:
    """Parse the ``--adapter-config`` value.

    Raises:
        pytest.UsageError: When ``raw`` is not a JSON object.
    """
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise pytest.UsageError(f"--adapter-config is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise pytest.UsageError(
            f"--adapter-config must be a JSON object, got {type(value).__name__}"
        )
    return value


def resolve_adapter_config(
    port: str, adapter: str, overrides: dict[str, Any]
) -> dict[str, Any]:
    """Return the configuration for ``adapter`` on ``port``.

    The built-in row for the adapter, or ``{"provider": adapter}`` when it has
    none, with ``overrides`` merged over it.

    Raises:
        ConfigurationError: When the port's registry does not know ``adapter``.
    """
    REGISTRIES[port].get(adapter)
    base = BUILTIN_ADAPTER_CONFIGS.get((port, adapter), {"provider": adapter})
    return copy.deepcopy({**base, **overrides})


def missing_capability(
    adapter: str,
    declared: Flag | None,
    requires: list[tuple[Flag, ...]],
    requires_any: list[tuple[Flag, ...]],
) -> str | None:
    """Return why ``adapter`` cannot run a test gated on these flags, or ``None``.

    ``requires`` holds the flags of each ``requires`` marker, all of which the
    adapter must declare. ``requires_any`` holds the flags of each
    ``requires_any`` marker, one of which it must declare.
    """
    if declared is None:
        return f"{adapter} declares no capabilities"
    for flags in requires:
        for flag in flags:
            if flag & declared != flag:
                return f"{adapter} does not declare {flag.name}"
    for flags in requires_any:
        if not any(flag & declared == flag for flag in flags):
            names = " or ".join(str(flag.name) for flag in flags)
            return f"{adapter} does not declare {names}"
    return None


def _port_for(request: pytest.FixtureRequest) -> str | None:
    return request.config.getoption("port", default=None) or port_of(request.node.path)


def _require_port(request: pytest.FixtureRequest) -> str:
    port = _port_for(request)
    if port is None:
        pytest.fail(
            f"{request.node.nodeid} is not under tests/conformance/<port>/ "
            f"and no --port was given",
            pytrace=False,
        )
    return port


def _adapter_name(request: pytest.FixtureRequest, port: str) -> str:
    return request.config.getoption("adapter", default=None) or DEFAULT_ADAPTERS[port]


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def adapter_config(request: pytest.FixtureRequest) -> dict[str, Any]:
    """The configuration of the adapter under test."""
    port = _require_port(request)
    return resolve_adapter_config(
        port,
        _adapter_name(request, port),
        parse_adapter_config(request.config.getoption("adapter_config", default=None)),
    )


@pytest.fixture(autouse=True)
def test_domain(request: pytest.FixtureRequest) -> Iterator[Domain | None]:
    """A domain whose default adapter for the test's port is the one under test.

    ``None`` for a test outside a port folder, or one marked ``no_test_domain``.
    """
    port = _port_for(request)
    if port is None or "no_test_domain" in request.keywords:
        yield None
        return

    domain = Domain(name="Conformance")
    # The domain adds keys to the configuration it is given, so it gets a copy
    # and the ``adapter_config`` fixture keeps the resolved value.
    CONFIGURE[port](domain, copy.deepcopy(request.getfixturevalue("adapter_config")))
    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"
    domain.config["message_processing"] = "sync"
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain


@pytest.fixture
def adapter(request: pytest.FixtureRequest, test_domain: Domain | None) -> Any:
    """The adapter under test, as the domain's container for its port holds it."""
    port = _require_port(request)
    if test_domain is None:
        pytest.fail(f"{request.node.nodeid} has no test domain", pytrace=False)
    return ADAPTER_OF[port](test_domain)


@pytest.fixture(autouse=True)
def run_around_tests(
    request: pytest.FixtureRequest, test_domain: Domain | None
) -> Iterator[None]:
    """Reset the adapter under test after each test."""
    yield

    if test_domain is not None:
        port = _require_port(request)
        reset_and_close(port, ADAPTER_OF[port](test_domain))


@pytest.fixture(autouse=True)
def _skip_unless_adapter_declares(
    request: pytest.FixtureRequest, run_around_tests: None
) -> None:
    """Skip a ``requires``/``requires_any`` test the adapter has no flags for."""
    # Depending on ``run_around_tests`` registers the reset and close before
    # this fixture can skip, so a skipped test still releases the adapter.
    requires = [marker.args for marker in request.node.iter_markers("requires")]
    requires_any = [marker.args for marker in request.node.iter_markers("requires_any")]
    if not requires and not requires_any:
        return

    port = _require_port(request)
    declared = getattr(request.getfixturevalue("adapter"), "capabilities", None)
    reason = missing_capability(
        _adapter_name(request, port), declared, requires, requires_any
    )
    if reason is not None:
        pytest.skip(reason)
