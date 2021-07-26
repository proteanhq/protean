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
        "--sendgrid", action="store_true", default=False, help="Run Sendgrid tests"
    )


def pytest_collection_modifyitems(config, items):
    """Configure special markers on tests, so as to control execution"""
    run_slow = (
        run_pending
    ) = (
        run_sqlite
    ) = run_postgresql = run_elasticsearch = run_redis = run_sendgrid = False

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

    if config.getoption("--sendgrid"):
        run_sendgrid = True

    skip_slow = pytest.mark.skip(reason="need --slow option to run")
    skip_pending = pytest.mark.skip(reason="need --pending option to run")
    skip_sqlite = pytest.mark.skip(reason="need --sqlite option to run")
    skip_postgresql = pytest.mark.skip(reason="need --postgresql option to run")
    skip_elasticsearch = pytest.mark.skip(reason="need --elasticsearch option to run")
    skip_redis = pytest.mark.skip(reason="need --redis option to run")
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
        if "sendgrid" in item.keywords and run_sendgrid is False:
            item.add_marker(skip_sendgrid)


@pytest.fixture(autouse=True)
def test_domain():
    from protean.domain import Domain

    domain = Domain("Test")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    with domain.domain_context():
        yield domain


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):

    yield

    # FIXME Providers has to become a MutableMapping
    for provider in test_domain.providers.providers_list():
        provider._data_reset()

    for _, broker in test_domain.brokers.items():
        broker._data_reset()

    for _, cache in test_domain.caches.items():
        cache.flush_all()
