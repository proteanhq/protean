import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain():
    """Auto-used domain fixture for all stream subscription tests."""
    domain = initialize_domain(name="Stream Subscription Tests", root_path=__file__)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain
