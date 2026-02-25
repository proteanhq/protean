"""Adapter conformance pytest plugin.

Provides fixtures, markers, and hooks to run Protean's generic database
adapter conformance tests against any provider.

This plugin is NOT auto-registered via ``pytest11``.  Load it explicitly
in a conftest.py::

    pytest_plugins = ["protean.integrations.pytest.adapter_conformance"]

Then point pytest at the generic conformance test directory::

    pytest "$(python -c 'from protean.testing import get_generic_test_dir; print(get_generic_test_dir())')"

CLI options
-----------
``--db``
    Known provider key (MEMORY, POSTGRESQL, SQLITE, MSSQL, ELASTICSEARCH).
``--db-provider``
    Provider name for custom/external adapters (e.g. ``dynamodb``).
``--db-uri``
    Database connection URI for custom adapters.
``--db-extra``
    JSON string of extra provider config (e.g. ``'{"pool_size": 5}'``).

Fixture overrides
-----------------
External adapter packages can override ``db_config`` in their own
conftest.py for full control over provider configuration::

    @pytest.fixture(scope="session")
    def db_config():
        return {
            "provider": "dynamodb",
            "database_uri": "dynamodb://localhost:8000",
            "region": "us-east-1",
        }
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest

from protean.port.provider import DatabaseCapabilities

# ---------------------------------------------------------------------------
# Built-in provider configurations (mirrors tests/conftest.py)
# ---------------------------------------------------------------------------
BUILTIN_DB_CONFIGS: dict[str, dict[str, Any]] = {
    "MEMORY": {"provider": "memory"},
    "POSTGRESQL": {
        "provider": "postgresql",
        "database_uri": "postgresql://postgres:postgres@localhost:5432/postgres",
        "pool_size": 1,
        "max_overflow": 2,
    },
    "ELASTICSEARCH": {
        "provider": "elasticsearch",
        "database": "elasticsearch",
        "database_uri": {"hosts": ["localhost"]},
    },
    "SQLITE": {
        "provider": "sqlite",
        "database_uri": "sqlite:///test.db",
    },
    "MSSQL": {
        "provider": "mssql",
        "database_uri": (
            "mssql+pyodbc://sa:Protean123!@localhost:1433/master"
            "?driver=ODBC+Driver+18+for+SQL+Server"
            "&TrustServerCertificate=yes&Encrypt=yes&MARS_Connection=yes"
        ),
        "pool_size": 1,
        "max_overflow": 2,
    },
}

# ---------------------------------------------------------------------------
# Capability marker → DatabaseCapabilities mapping
# (mirrors tests/adapters/repository/generic/conftest.py)
# ---------------------------------------------------------------------------
MARKER_TO_CAPABILITY: dict[str, DatabaseCapabilities] = {
    "basic_storage": DatabaseCapabilities.BASIC_STORAGE,
    "transactional": (
        DatabaseCapabilities.TRANSACTIONS | DatabaseCapabilities.SIMULATED_TRANSACTIONS
    ),
    "atomic_transactions": DatabaseCapabilities.TRANSACTIONS,
    "raw_queries": DatabaseCapabilities.RAW_QUERIES,
    "schema_management": DatabaseCapabilities.SCHEMA_MANAGEMENT,
    "native_json": DatabaseCapabilities.NATIVE_JSON,
    "native_array": DatabaseCapabilities.NATIVE_ARRAY,
}


# ===================================================================
# Pytest hooks
# ===================================================================


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register CLI options for adapter conformance testing."""
    group = parser.getgroup("protean-conformance", "Protean adapter conformance")

    # --db may already be defined by tests/conftest.py when running
    # inside Protean's own repository.
    try:
        group.addoption(
            "--db",
            action="store",
            default="MEMORY",
            help="Database provider key (e.g. MEMORY, POSTGRESQL)",
        )
    except ValueError:
        pass  # Already registered by another conftest

    group.addoption(
        "--db-provider",
        action="store",
        default=None,
        help="Provider name for custom adapters (e.g. 'dynamodb')",
    )
    group.addoption(
        "--db-uri",
        action="store",
        default=None,
        help="Database connection URI for custom adapters",
    )
    group.addoption(
        "--db-extra",
        action="store",
        default=None,
        help="JSON string of extra provider config (e.g. '{\"pool_size\": 5}')",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register capability markers so ``--strict-markers`` doesn't complain."""
    for marker_name in MARKER_TO_CAPABILITY:
        config.addinivalue_line(
            "markers",
            f"{marker_name}: database capability conformance test",
        )
    config.addinivalue_line(
        "markers", "database: tests requiring database setup/teardown"
    )
    config.addinivalue_line(
        "markers", "no_test_domain: opt out of the autouse test_domain fixture"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-inject ``db`` fixture and annotate capability requirements."""
    capability_markers = list(MARKER_TO_CAPABILITY.keys())

    for item in items:
        # Auto-inject db fixture for capability-marked tests
        needs_db = bool(item.get_closest_marker("database"))
        if not needs_db:
            for marker_name in capability_markers:
                if item.get_closest_marker(marker_name):
                    needs_db = True
                    break

        if needs_db and "db" not in item.fixturenames:
            item.fixturenames.append("db")

        # Annotate each item with its required capability
        for marker_name, required_caps in MARKER_TO_CAPABILITY.items():
            if item.get_closest_marker(marker_name) is not None:
                item._database_required_capability = (marker_name, required_caps)
                break


# ===================================================================
# Fixtures
# ===================================================================


def resolve_db_config(
    db_key: str = "MEMORY",
    db_provider: str | None = None,
    db_uri: str | None = None,
    db_extra: str | None = None,
) -> dict[str, Any]:
    """Resolve database provider configuration from CLI options.

    Priority:
    1. *db_provider* + *db_uri* (custom adapter)
    2. *db_key* mapped to a built-in config
    3. *db_key* value treated as provider name (fallback)

    This is a plain function so it can be tested independently of
    the pytest fixture machinery.
    """
    if db_provider is not None:
        cfg: dict[str, Any] = {"provider": db_provider}
        if db_uri:
            cfg["database_uri"] = db_uri
        if db_extra:
            cfg.update(json.loads(db_extra))
        return cfg

    if db_key in BUILTIN_DB_CONFIGS:
        return BUILTIN_DB_CONFIGS[db_key]

    # Unknown key — treat as provider name (lowercased)
    return {"provider": db_key.lower()}


@pytest.fixture(scope="session")
def db_config(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Resolve database provider configuration.

    See :func:`resolve_db_config` for resolution priority.
    Override this fixture in your conftest for full control.
    """
    return resolve_db_config(
        db_key=request.config.getoption("--db", default="MEMORY"),
        db_provider=request.config.getoption("--db-provider", default=None),
        db_uri=request.config.getoption("--db-uri", default=None),
        db_extra=request.config.getoption("--db-extra", default=None),
    )


@pytest.fixture(scope="session")
def store_config() -> dict[str, Any]:
    """Default event store config for conformance tests."""
    return {"provider": "memory"}


@pytest.fixture(scope="session")
def broker_config() -> dict[str, Any]:
    """Default broker config for conformance tests."""
    return {"provider": "inline"}


@pytest.fixture(autouse=True)
def test_domain(
    db_config: dict[str, Any],
    store_config: dict[str, Any],
    broker_config: dict[str, Any],
    request: pytest.FixtureRequest,
):
    """Create a Domain configured with the adapter under test.

    Skipped for tests marked ``no_test_domain``.
    """
    if "no_test_domain" in request.keywords:
        yield
        return

    from protean.domain import Domain

    domain = Domain(name="AdapterConformanceTest")

    domain.config["databases"]["default"] = db_config
    domain.config["event_store"] = store_config
    domain.config["brokers"]["default"] = broker_config

    domain.config["command_processing"] = "sync"
    domain.config["event_processing"] = "sync"
    domain.config["message_processing"] = "sync"

    domain._initialize()

    with domain.domain_context():
        yield domain


@pytest.fixture
def db(test_domain):
    """Create and drop database artifacts around each test.

    Auto-injected for tests marked with ``database`` or any
    capability marker via ``pytest_collection_modifyitems``.
    """
    test_domain.providers["default"]._create_database_artifacts()

    yield

    test_domain.providers["default"]._drop_database_artifacts()
    test_domain.registry._reset()


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):
    """Reset all data stores after each test."""
    yield

    if test_domain:
        for provider_name in test_domain.providers:
            provider = test_domain.providers[provider_name]
            try:
                provider._data_reset()
            finally:
                provider.close()

        for broker_name in test_domain.brokers:
            broker = test_domain.brokers[broker_name]
            broker._data_reset()

        for cache_name in test_domain.caches:
            cache = test_domain.caches[cache_name]
            cache.flush_all()

        if test_domain.event_store.store:
            try:
                test_domain.event_store.store._data_reset()
            finally:
                test_domain.event_store.store.close()


@pytest.fixture(autouse=True)
def auto_set_and_close_loop():
    """Create a fresh asyncio event loop for each test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    yield

    if not loop.is_closed():
        loop.close()
    asyncio.set_event_loop(None)


@pytest.fixture(autouse=True)
def _skip_if_provider_lacks_capability(
    request: pytest.FixtureRequest,
    test_domain,
):
    """Skip the test if the provider lacks the required capability."""
    cap_info = getattr(request.node, "_database_required_capability", None)
    if cap_info is None:
        return

    marker_name, required_caps = cap_info
    provider = test_domain.providers["default"]

    if marker_name == "transactional":
        if not provider.has_any_capability(required_caps):
            pytest.skip(
                f"Provider '{provider.name}' ({provider.__class__.__name__}) "
                f"lacks transaction support (real or simulated)"
            )
    else:
        if not provider.has_all_capabilities(required_caps):
            pytest.skip(
                f"Provider '{provider.name}' ({provider.__class__.__name__}) "
                f"lacks required capability: {marker_name}"
            )


@pytest.fixture(scope="session", autouse=True)
def cleanup_logging_handlers():
    """Avoid closed-resource errors from logging after async tests."""
    try:
        yield
    finally:
        for handler in logging.root.handlers[:]:
            if isinstance(handler, logging.StreamHandler):
                logging.root.removeHandler(handler)
