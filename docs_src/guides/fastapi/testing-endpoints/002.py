# --8<-- [start:api-imports]
from fastapi import FastAPI

from protean import Domain
from protean.integrations.fastapi import DomainContextMiddleware

# --8<-- [end:api-imports]
# isort: split

# --8<-- [start:conftest-imports]
import pytest

from protean.integrations.pytest import DomainFixture

# --8<-- [end:conftest-imports]
# isort: split

from protean.fields import String
from protean.utils.globals import current_domain

# --8<-- [start:api]
identity_domain = Domain(name="Identity")
ordering_domain = Domain(name="Ordering")

app = FastAPI()
app.add_middleware(
    DomainContextMiddleware,
    route_domain_map={
        "/customers": identity_domain,
        "/orders": ordering_domain,
    },
)
# --8<-- [end:api]


@identity_domain.aggregate
class Customer:
    name = String(required=True)


@ordering_domain.aggregate
class Order:
    customer_name = String(required=True)


@app.post("/customers")
def register_customer(payload: dict) -> dict:
    customer = Customer(name=payload["name"])
    current_domain.repository_for(Customer).add(customer)
    return {"id": customer.id, "domain": current_domain.name}


@app.post("/orders")
def place_order(payload: dict) -> dict:
    order = Order(customer_name=payload["customer_name"])
    current_domain.repository_for(Order).add(order)
    return {"id": order.id, "domain": current_domain.name}


# --8<-- [start:conftest]
@pytest.fixture(scope="session")
def identity_fixture():
    identity_domain.config["command_processing"] = "sync"
    identity_domain.config["event_processing"] = "sync"
    fixture = DomainFixture(identity_domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(scope="session")
def ordering_fixture():
    ordering_domain.config["command_processing"] = "sync"
    ordering_domain.config["event_processing"] = "sync"
    fixture = DomainFixture(ordering_domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(identity_fixture, ordering_fixture):
    with identity_fixture.domain_context():
        with ordering_fixture.domain_context():
            yield


# --8<-- [end:conftest]
