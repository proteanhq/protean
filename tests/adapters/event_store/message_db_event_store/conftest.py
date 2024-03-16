import pytest

from tests.shared import initialize_domain


@pytest.fixture
def test_domain():
    domain = initialize_domain(__file__)

    with domain.domain_context():
        yield domain
