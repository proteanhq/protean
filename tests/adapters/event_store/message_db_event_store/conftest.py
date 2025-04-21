import pytest

from tests.shared import initialize_domain


@pytest.fixture
def test_domain():
    domain = initialize_domain(name="Message DB Event Store Tests", root_path=__file__)

    with domain.domain_context():
        yield domain
