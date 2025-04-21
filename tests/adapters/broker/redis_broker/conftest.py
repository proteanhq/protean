import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain(name="Redis Broker Tests", root_path=__file__)

    # We initialize and load default configuration into the domain here
    #   so that test cases that don't need explicit domain setup can
    #   still function.
    domain._initialize()

    with domain.domain_context():
        yield domain
