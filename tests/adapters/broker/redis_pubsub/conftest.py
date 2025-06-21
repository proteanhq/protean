import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain(name="Redis PubSub Broker Tests", root_path=__file__)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain
