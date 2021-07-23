import os

import pytest

from redis import Redis


def initialize_domain():
    from protean.domain import Domain

    domain = Domain("Redis Broker Tests")

    # Construct relative path to config file
    current_path = os.path.abspath(os.path.dirname(__file__))
    config_path = os.path.join(current_path, "./config.py")

    if os.path.exists(config_path):
        domain.config.from_pyfile(config_path)

    domain.domain_context().push()
    return domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain()

    yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_redis():
    # Initialize Redis
    # FIXME

    yield

    # Close connection to Redis
    # FIXME


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):

    yield

    if ("default") in test_domain.brokers:
        test_domain.brokers["default"]._data_reset()

    if test_domain.providers.has_provider("default"):
        test_domain.get_provider("default")._data_reset()
