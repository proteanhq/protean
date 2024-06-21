import pytest

from tests.shared import initialize_domain


@pytest.fixture(autouse=True)
def test_domain():
    domain = initialize_domain(__file__, "Celery Broker Tests")
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain
