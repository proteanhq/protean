import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain(__file__)

    with domain.domain_context():
        yield domain


@pytest.fixture(scope="session", autouse=True)
def setup_redis():
    # Initialize Redis
    # FIXME

    yield

    # Close connection to Redis
    # FIXME
