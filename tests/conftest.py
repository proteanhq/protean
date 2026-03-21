"""Module to setup Factories and other required artifacts for tests"""

import asyncio
import logging
import os
import sys

import pytest

from tests.shared import (
    ELASTICSEARCH_URI,
    MESSAGE_DB_URI,
    MSSQL_URI,
    POSTGRES_URI,
    REDIS_URI,
)


def pytest_configure(config):
    # Insert the docs_src path into sys.path so that we can import elements from there
    #   in our tests
    docs_src_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../docs_src")
    )
    sys.path.insert(0, docs_src_path)


# ---------------------------------------------------------------------------
# Collection-time ignoring of adapter-specific test directories
# ---------------------------------------------------------------------------
#
# Tests under these directories import optional packages (sqlalchemy, redis,
# elasticsearch, opentelemetry, etc.) at the top level.  When those packages
# are not installed, collection fails with ImportError *before* marker-based
# skip logic in ``pytest_collection_modifyitems`` can run.
#
# ``pytest_ignore_collect`` fires before import, so returning True for a
# directory prevents pytest from descending into it at all.

# Maps directory paths (relative to repo root) to the CLI flags that
# enable collection.  When *none* of the listed flags are passed, the
# directory is silently ignored.
_ADAPTER_DIR_FLAGS: dict[str, list[str]] = {
    "tests/adapters/repository/sqlalchemy_repo": [
        "--postgresql",
        "--sqlite",
        "--mssql",
    ],
    "tests/adapters/database_model/sqlalchemy_model": [
        "--postgresql",
        "--sqlite",
        "--mssql",
    ],
    "tests/adapters/repository/elasticsearch_repo": ["--elasticsearch"],
    "tests/adapters/database_model/elasticsearch_model": ["--elasticsearch"],
    "tests/adapters/broker/redis": ["--redis"],
    "tests/adapters/broker/redis_pubsub": ["--redis"],
    "tests/adapters/cache/redis_cache": ["--redis"],
    "tests/adapters/event_store/message_db_event_store": ["--message_db"],
    "tests/adapters/email/sendgrid_email": ["--sendgrid"],
}

# Individual test files that require opentelemetry SDK.  There is no CLI
# flag for these; they are ignored when the package is not installed.
_TELEMETRY_TEST_FILES: set[str] = {
    "tests/server/test_server_telemetry_spans.py",
    "tests/server/test_telemetry_integration.py",
    "tests/server/test_telemetry_metrics.py",
    "tests/server/test_telemetry_propagation.py",
    "tests/server/test_telemetry_spans.py",
    "tests/utils/test_telemetry.py",
    "tests/integrations/fastapi/test_telemetry.py",
}

_otel_available: bool | None = None


def _is_opentelemetry_available() -> bool:
    global _otel_available
    if _otel_available is None:
        try:
            import opentelemetry.sdk.trace  # noqa: F401

            _otel_available = True
        except ImportError:
            _otel_available = False
    return _otel_available


def pytest_ignore_collect(collection_path, config):
    """Ignore adapter-specific test directories when their CLI flags are not set.

    This prevents ImportError during collection when optional packages
    (sqlalchemy, redis, elasticsearch, opentelemetry, etc.) are not installed.
    """
    try:
        rel = collection_path.relative_to(config.rootpath)
    except ValueError:
        return None

    rel_str = str(rel)

    # Check adapter directories
    for dir_prefix, flags in _ADAPTER_DIR_FLAGS.items():
        if rel_str == dir_prefix or rel_str.startswith(dir_prefix + os.sep):
            if not any(config.getoption(flag, default=False) for flag in flags):
                return True
            return None

    # Check telemetry test files
    if rel_str in _TELEMETRY_TEST_FILES and not _is_opentelemetry_available():
        return True

    return None


def pytest_addoption(parser):
    """Additional options for running tests with pytest"""
    parser.addoption(
        "--slow", action="store_true", default=False, help="Run slow tests"
    )
    parser.addoption(
        "--pending", action="store_true", default=False, help="Show pending tests"
    )
    parser.addoption(
        "--sqlite", action="store_true", default=False, help="Run Sqlite tests"
    )
    parser.addoption(
        "--postgresql", action="store_true", default=False, help="Run Postgresql tests"
    )
    parser.addoption(
        "--mssql", action="store_true", default=False, help="Run MSSQL tests"
    )
    parser.addoption(
        "--elasticsearch",
        action="store_true",
        default=False,
        help="Run Elasticsearch tests",
    )
    parser.addoption(
        "--redis", action="store_true", default=False, help="Run Redis based tests"
    )
    parser.addoption(
        "--message_db", action="store_true", default=False, help="Run Redis based tests"
    )
    parser.addoption(
        "--sendgrid", action="store_true", default=False, help="Run Sendgrid tests"
    )

    # Options to run Database tests
    parser.addoption(
        "--database",
        action="store_true",
        default=False,
        help="Database test marker",
    )
    parser.addoption(
        "--db",
        action="store",
        default="MEMORY",
        help="Run tests against a Database type",
    )

    # Options to run EventStore tests
    parser.addoption(
        "--eventstore",
        action="store_true",
        default=False,
        help="Eventstore test marker",
    )
    parser.addoption(
        "--store",
        action="store",
        default="MEMORY",
        help="Run tests against a Eventstore type",
    )

    # Options to run Broker tests
    parser.addoption(
        "--broker_common",
        action="store_true",
        default=False,
        help="Broker test marker",
    )
    parser.addoption(
        "--broker",
        action="store",
        default="INLINE",
        help="Run tests against a Broker type",
    )


def pytest_collection_modifyitems(config, items):
    """Configure special markers on tests, so as to control execution"""
    run_slow = run_pending = run_sqlite = run_postgresql = run_elasticsearch = (
        run_redis
    ) = run_message_db = run_sendgrid = run_mssql = False

    if config.getoption("--slow"):
        # --slow given in cli: do not skip slow tests
        run_slow = True

    if config.getoption("--pending"):
        run_pending = True

    if config.getoption("--sqlite"):
        run_sqlite = True

    if config.getoption("--postgresql"):
        run_postgresql = True

    if config.getoption("--elasticsearch"):
        run_elasticsearch = True

    if config.getoption("--mssql"):
        run_mssql = True

    if config.getoption("--redis"):
        run_redis = True

    if config.getoption("--message_db"):
        run_message_db = True

    if config.getoption("--sendgrid"):
        run_sendgrid = True

    skip_slow = pytest.mark.skip(reason="need --slow option to run")
    skip_pending = pytest.mark.skip(reason="need --pending option to run")
    skip_sqlite = pytest.mark.skip(reason="need --sqlite option to run")
    skip_postgresql = pytest.mark.skip(reason="need --postgresql option to run")
    skip_elasticsearch = pytest.mark.skip(reason="need --elasticsearch option to run")
    skip_mssql = pytest.mark.skip(reason="need --mssql option to run")
    skip_redis = pytest.mark.skip(reason="need --redis option to run")
    skip_message_db = pytest.mark.skip(reason="need --message_db option to run")
    skip_sendgrid = pytest.mark.skip(reason="need --sendgrid option to run")

    for item in items:
        if "slow" in item.keywords and run_slow is False:
            item.add_marker(skip_slow)
        if "pending" in item.keywords and run_pending is False:
            item.add_marker(skip_pending)
        if "sqlite" in item.keywords and run_sqlite is False:
            item.add_marker(skip_sqlite)
        if "postgresql" in item.keywords and run_postgresql is False:
            item.add_marker(skip_postgresql)
        if "elasticsearch" in item.keywords and run_elasticsearch is False:
            item.add_marker(skip_elasticsearch)
        if "mssql" in item.keywords and run_mssql is False:
            item.add_marker(skip_mssql)
        if "redis" in item.keywords and run_redis is False:
            item.add_marker(skip_redis)
        if "message_db" in item.keywords and run_message_db is False:
            item.add_marker(skip_message_db)
        if "sendgrid" in item.keywords and run_sendgrid is False:
            item.add_marker(skip_sendgrid)

        # Automatically add the `db` fixture to tests marked with `database`
        #   or any database capability marker, to setup and destroy database artifacts
        if item.get_closest_marker("database"):
            item.fixturenames.append("db")
        else:
            capability_markers = [
                "basic_storage",
                "transactional",
                "atomic_transactions",
                "raw_queries",
                "schema_management",
                "native_json",
                "native_array",
                "sa_provider",
            ]
            for marker_name in capability_markers:
                if item.get_closest_marker(marker_name):
                    item.fixturenames.append("db")
                    break  # Only need to add db once


@pytest.fixture(scope="session")
def store_config(request):
    try:
        return {
            "MEMORY": {
                "provider": "memory",
            },
            "MESSAGE_DB": {
                "provider": "message_db",
                "database_uri": MESSAGE_DB_URI,
            },
        }[request.config.getoption("--store", "MEMORY")]
    except KeyError as e:
        raise KeyError(
            f"Invalid store option: {request.config.getoption('--store')}"
        ) from e


@pytest.fixture(scope="session")
def db_config(request):
    try:
        return {
            "MEMORY": {"provider": "memory"},
            "POSTGRESQL": {
                "provider": "postgresql",
                "database_uri": POSTGRES_URI,
                "pool_size": 1,
                "max_overflow": 2,
            },
            "ELASTICSEARCH": {
                "provider": "elasticsearch",
                "database": "elasticsearch",
                "database_uri": ELASTICSEARCH_URI,
            },
            "SQLITE": {
                "provider": "sqlite",
                "database_uri": "sqlite:///test.db",
            },
            "MSSQL": {
                "provider": "mssql",
                "database_uri": MSSQL_URI,
                "pool_size": 1,
                "max_overflow": 2,
            },
        }[request.config.getoption("--db", "MEMORY")]
    except KeyError as e:
        raise KeyError(
            f"Invalid database option: {request.config.getoption('--db')}"
        ) from e


@pytest.fixture(scope="session")
def broker_config(request):
    """
    Returns the broker configuration based on the command line option.

    The default broker is `INLINE`.

    Redis brokers are connected to different databases, because tests
    may run in parallel, and we don't want them to interfere with each other.
    """
    return {
        "INLINE": {"provider": "inline"},
        "REDIS": {
            "provider": "redis",
            "URI": f"{REDIS_URI}/2",
            "TTL": 300,
        },
        "REDIS_PUBSUB": {
            "provider": "redis_pubsub",
            "URI": f"{REDIS_URI}/3",
            "TTL": 300,
        },
    }[request.config.getoption("--broker", "INLINE")]


@pytest.fixture(autouse=True)
def test_domain(db_config, store_config, broker_config, request):
    if "no_test_domain" in request.keywords:
        yield
    else:
        from protean.domain import Domain

        domain = Domain(name="Test")

        domain.config["databases"]["default"] = db_config
        domain.config["event_store"] = store_config
        domain.config["brokers"]["default"] = broker_config

        domain.config["command_processing"] = "sync"
        domain.config["event_processing"] = "sync"
        domain.config["message_processing"] = "sync"

        # We initialize and load default configuration into the domain here
        #   so that test cases that don't need explicit domain setup can
        #   still function.
        domain._initialize()

        with domain.domain_context():
            yield domain


@pytest.fixture()
def broker(test_domain):
    return test_domain.brokers["default"]


@pytest.fixture
def db(test_domain):
    """This fixture is automatically associated with all tests marked
    `database`. The association is done in `pytest_collection_modifyitems`
    method.

    It helps create and drop db structures of registered
    aggregates, entities, and projections.
    """
    # Call provider to create structures
    test_domain.providers["default"]._create_database_artifacts()

    yield

    # Drop structures
    test_domain.providers["default"]._drop_database_artifacts()

    # Remove registry content so that `_data_reset()` called on providers
    #   later (in `run_around_tests`) has no effect
    test_domain.registry._reset()


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):
    yield

    if test_domain:
        # FIXME Providers has to become a MutableMapping
        for provider_name in test_domain.providers:
            provider = test_domain.providers[provider_name]
            try:
                provider._data_reset()
            finally:
                # Always close provider connections to prevent connection leaks,
                # even if _data_reset() fails (e.g., tables already dropped)
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
                # Always close event store connections to prevent pool exhaustion,
                # even if _data_reset() fails
                test_domain.event_store.store.close()


@pytest.fixture(autouse=True)
def auto_set_and_close_loop():
    # Create and set a new loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    yield

    # Cancel any pending tasks and close all loops that may have been created
    # during the test (e.g. Engine creates its own loop).
    try:
        current_loop = asyncio.get_event_loop()
    except RuntimeError:
        current_loop = None

    for active_loop in {loop, current_loop} - {None}:
        if active_loop.is_closed():
            continue
        pending = [t for t in asyncio.all_tasks(active_loop) if not t.done()]
        for task in pending:
            task.cancel()
        if pending and not active_loop.is_running():
            active_loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True)
            )
        if not active_loop.is_running():
            active_loop.close()

    asyncio.set_event_loop(None)  # Explicitly unset the loop


@pytest.fixture(scope="session", autouse=True)
def cleanup_logging_handlers():
    """This fixture avoids closed resources error on logging module
    after the async app tests have been actually finished.
    See: https://github.com/pytest-dev/pytest/issues/5502
    """
    try:
        yield
    finally:
        for handler in logging.root.handlers[:]:
            if isinstance(handler, logging.StreamHandler):
                logging.root.removeHandler(handler)
