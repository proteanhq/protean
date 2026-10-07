# --8<-- [start:domain]
from protean import Domain
from protean.fields import Float, HasMany, Integer, String

domain = Domain(name="Shop")


@domain.entity(part_of="Order")
class OrderItem:
    product_id: String(max_length=50, required=True)
    quantity: Integer(min_value=1, required=True)


@domain.aggregate
class Ticket:
    title: String(max_length=100, required=True)
    status: String(max_length=20, default="PENDING")


@domain.repository(part_of=Ticket)
class TicketRepository:
    def find_pending(self, limit):
        query = self._dao.query.filter(status="PENDING").limit(limit)
        return query.all(with_total=False).items

    def count_pending(self):
        return self._dao.query.filter(status="PENDING").count()


@domain.aggregate
class Order:
    customer_name: String(max_length=100, required=True)
    status: String(max_length=20, default="PENDING")
    total_amount: Float(default=0.0)
    items = HasMany(OrderItem)


# --8<-- [end:domain]


# --8<-- [start:conftest]
import pytest

from protean.integrations.pytest import DomainFixture


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


# --8<-- [start:imports]
import re

import pytest

from protean.integrations.pytest import (
    assert_no_overfetch,
    assert_no_subquery_wrap,
    assert_query_count,
    capture_queries,
)

# --8<-- [end:imports]


# --8<-- [start:query_count]
@pytest.mark.database
def test_poll_issues_a_single_query(ticket_repo, seeded_tickets):
    with assert_query_count(1):
        ticket_repo.find_pending(limit=10)


# --8<-- [end:query_count]


# --8<-- [start:subquery_wrap]
@pytest.mark.database
def test_count_uses_a_flat_count(ticket_repo):
    with assert_no_subquery_wrap():
        ticket_repo.count_pending()


# --8<-- [end:subquery_wrap]


# --8<-- [start:overfetch]
@pytest.mark.database
def test_poll_does_not_overfetch(ticket_repo, seeded_tickets):
    with assert_no_overfetch(expected_returned=10):
        ticket_repo.find_pending(limit=10)


# --8<-- [end:overfetch]


# --8<-- [start:capture_queries]
@pytest.mark.database
def test_parent_inserted_before_children(order_repo, order):
    with capture_queries() as captured:
        order_repo.add(order)

    tables = [
        re.search(r'INSERT INTO "?(\w+)', statement, re.IGNORECASE).group(1).lower()
        for statement, _params in captured
        if statement.lstrip().upper().startswith("INSERT")
    ]
    assert tables, "no INSERTs captured; the hook did not fire"
    assert tables.index("order") < tables.index("order_item")


# --8<-- [end:capture_queries]


# --8<-- [start:explicit_engine]
@pytest.mark.database
def test_poll_on_an_explicit_engine(ticket_repo):
    my_engine = domain.providers["default"]._engine

    with assert_query_count(1, engine=my_engine):
        ticket_repo.find_pending(limit=10)


# --8<-- [end:explicit_engine]
