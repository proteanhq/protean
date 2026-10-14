# --8<-- [start:conftest]
import pytest
from ticketing import Order, OrderItem, Ticket, domain

from protean.integrations.pytest import DomainFixture


def pytest_configure(config):
    config.addinivalue_line("markers", "database: runs against a real SQL backend")


@pytest.fixture(scope="session")
def app_fixture(tmp_path_factory):
    # Query-shape assertions need a SQLAlchemy provider. SQLite needs no server.
    database = tmp_path_factory.getbasetemp() / "shop.db"
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": f"sqlite:///{database}",
    }

    fixture = DomainFixture(domain)
    fixture.setup()
    yield fixture
    fixture.teardown()


@pytest.fixture(autouse=True)
def _ctx(app_fixture):
    with app_fixture.domain_context():
        yield


@pytest.fixture
def ticket_repo():
    return domain.repository_for(Ticket)


@pytest.fixture
def seeded_tickets(ticket_repo):
    for number in range(20):
        ticket_repo.add(Ticket(title=f"Ticket {number}"))


@pytest.fixture
def order_repo():
    return domain.repository_for(Order)


@pytest.fixture
def order():
    return Order(
        customer_name="Alice",
        items=[OrderItem(product_id="dune", quantity=2)],
    )


# --8<-- [end:conftest]
