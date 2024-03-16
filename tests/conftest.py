"""Module to setup Factories and other required artifacts for tests

    isort:skip_file
"""

import os
import pytest


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


def pytest_collection_modifyitems(config, items):
    """Configure special markers on tests, so as to control execution"""
    run_slow = run_pending = run_sqlite = run_postgresql = run_elasticsearch = (
        run_redis
    ) = run_message_db = run_sendgrid = False

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
                "PROVIDER": "protean.adapters.event_store.memory.MemoryEventStore",
            },
            "MESSAGE_DB": {
                "PROVIDER": "protean.adapters.event_store.message_db.MessageDBStore",
                "DATABASE_URI": "postgresql://message_store@localhost:5433/message_store",
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
            "MEMORY": {"PROVIDER": "protean.adapters.MemoryProvider"},
            "POSTGRESQL": {
                "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
                "DATABASE": "POSTGRESQL",
                "DATABASE_URI": "postgresql://postgres:postgres@localhost:5432/postgres",
            },
            "ELASTICSEARCH": {
                "PROVIDER": "protean.adapters.repository.elasticsearch.ESProvider",
                "DATABASE": "ELASTICSEARCH",
                "DATABASE_URI": {"hosts": ["localhost"]},
            },
            "SQLITE": {
                "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
                "DATABASE": "SQLITE",
                "DATABASE_URI": "sqlite:///test.db",
            },
        }[request.config.getoption("--db", "MEMORY")]
    except KeyError as e:
        raise KeyError(
            f"Invalid database option: {request.config.getoption('--db')}"
        ) from e


@pytest.fixture(autouse=True)
def test_domain(db_config, store_config, request):
    if "no_test_domain" in request.keywords:
        yield
    else:
        from protean.domain import Domain

        domain = Domain(__file__, "Test")

        # Construct relative path to config file
        current_path = os.path.abspath(os.path.dirname(__file__))
        config_path = os.path.join(current_path, "./config.py")

        if os.path.exists(config_path):
            domain.config.from_pyfile(config_path)

        domain.config["DATABASES"]["default"] = db_config
        domain.config["EVENT_STORE"] = store_config

        # Always reinitialize the domain after config changes
        domain.reinitialize()

        with domain.domain_context():
            yield domain


@pytest.fixture
def db(test_domain):
    """This fixture is automatically associated with all tests marked
    `database`. The association is done in `pytest_collection_modifyitems`
    method.

    It helps create and drop db structures of registered
    aggregates, entities, and views.
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
            provider._data_reset()

        for broker_name in test_domain.brokers:
            broker = test_domain.brokers[broker_name]
            broker._data_reset()

        for cache_name in test_domain.caches:
            cache = test_domain.caches[cache_name]
            cache.flush_all()

        test_domain.event_store.store._data_reset()
