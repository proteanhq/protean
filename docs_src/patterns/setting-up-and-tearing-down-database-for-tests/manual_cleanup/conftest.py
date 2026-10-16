import pytest
from orderdesk import domain


@pytest.fixture(scope="session", autouse=True)
def _domain():
    domain.init(traverse=False)
    with domain.domain_context():
        domain.setup_database()
        yield
        domain.drop_database()


# --8<-- [start:clean_data]
@pytest.fixture(autouse=True)
def clean_data():
    yield
    for provider in domain.providers.values():
        provider._data_reset()
    for broker in domain.brokers.values():
        broker._data_reset()
    domain.event_store.store._data_reset()


# --8<-- [end:clean_data]
