# --8<-- [start:fixture]
import pytest


@pytest.fixture(autouse=True)
def domain_context(test_domain):
    with test_domain.domain_context():
        yield


# --8<-- [end:fixture]
