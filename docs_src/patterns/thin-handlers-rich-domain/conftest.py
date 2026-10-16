# --8<-- [start:fixture]
import pytest
from refunds.domain import domain


@pytest.fixture
def test_domain():
    domain.init(traverse=False)
    with domain.domain_context():
        yield domain


# --8<-- [end:fixture]
