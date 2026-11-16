import pytest
from myapp import domain


@pytest.fixture(scope="session", autouse=True)
def _domain():
    domain.init(traverse=False)
    with domain.domain_context():
        yield


# --8<-- [start:manual_cleanup]
@pytest.fixture(autouse=True)
def clean_data():
    yield
    # Reset all adapter data after each test
    for provider in domain.databases.values():
        provider.clear()
    for broker in domain.brokers.values():
        broker.clear()
    domain.event_store.store.clear()


# --8<-- [end:manual_cleanup]
