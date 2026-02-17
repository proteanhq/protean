"""Module to setup Factories and other required artifacts for tests"""

import asyncio
import logging
import os
import sys

import pytest


def pytest_configure(config):
    # Insert the docs_src path into sys.path so that we can import elements from there
    #   in our tests
    docs_src_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "../docs_src")
    )
    sys.path.insert(0, docs_src_path)


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
        #   to setup and destroy database artifacts
        if item.get_closest_marker("database"):
            item.fixturenames.append("db")


@pytest.fixture(scope="session")
def store_config(request):
    try:
        return {
            "MEMORY": {
                "provider": "memory",
            },
            "MESSAGE_DB": {
                "provider": "message_db",
                "database_uri": "postgresql://message_store@localhost:5433/message_store",
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
                "database_uri": "mssql+pyodbc://sa:Protean123!@localhost:1433/master?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes&Encrypt=yes&MARS_Connection=yes",
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
            "URI": "redis://localhost:6379/2",
            "TTL": 300,
        },
        "REDIS_PUBSUB": {
            "provider": "redis_pubsub",
            "URI": "redis://localhost:6379/3",
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
            test_domain.event_store.store._data_reset()


@pytest.fixture(autouse=True)
def auto_set_and_close_loop():
    # Create and set a new loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    yield

    # Close the loop after the test
    if not loop.is_closed():
        loop.close()
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
