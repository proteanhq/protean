# --8<-- [start:conftest]
from uuid import uuid4

import pytest
from ordering_es import InitiatePayment, OrderConfirmed, OrderCreated, domain

from protean.integrations.pytest import DomainFixture


@pytest.fixture(scope="session")
def app_fixture():
    domain.config["event_processing"] = "sync"
    domain.config["command_processing"] = "sync"

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


# --8<-- [end:conftest]


# --8<-- [start:event_fixtures]
@pytest.fixture
def order_id():
    return str(uuid4())


@pytest.fixture
def order_created(order_id):
    return OrderCreated(order_id=order_id, customer="Alice", amount=99.99)


@pytest.fixture
def order_confirmed(order_id):
    return OrderConfirmed(order_id=order_id)


@pytest.fixture
def initiate_payment(order_id):
    return InitiatePayment(order_id=order_id, payment_id="pay-001")


# --8<-- [end:event_fixtures]
