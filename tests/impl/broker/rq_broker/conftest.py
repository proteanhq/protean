# Standard Library Imports
import os

# Protean
import pytest

from redis import Redis
from rq import get_current_connection, pop_connection, push_connection


def initialize_domain():
    from protean.domain import Domain

    domain = Domain("RQ Tests")

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


@pytest.fixture(scope="module")
def test_domain_for_worker():
    domain = initialize_domain()

    yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_redis():
    # Initialize Connection to Redis
    push_connection(Redis.from_url("redis://127.0.0.1:6379/2"))

    yield

    # Close connection to Redis
    pop_connection()


@pytest.fixture(autouse=True)
def run_around_tests(test_domain):

    yield

    conn = get_current_connection()
    conn.flushall()

    if test_domain.has_provider("default"):
        test_domain.get_provider("default")._data_reset()
