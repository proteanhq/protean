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
    for provider in domain.providers.values():
        provider._data_reset()
    for broker in domain.brokers.values():
        broker._data_reset()
    domain.event_store.store._data_reset()


# --8<-- [end:manual_cleanup]
