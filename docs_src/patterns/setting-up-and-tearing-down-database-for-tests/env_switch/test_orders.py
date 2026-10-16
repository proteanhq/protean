# --8<-- [start:tests]
import os

from orderdesk import Order, domain


def test_the_provider_follows_test_db():
    provider = domain.providers["default"].conn_info["provider"]
    assert provider == os.environ.get("TEST_DB", "memory")


# Each test starts by checking the table is empty, so whichever runs second
# fails if data leaked from the first. On SQLite the first query also fails
# if setup() did not create the table.
def test_first_order_round_trips():
    repo = domain.repository_for(Order)
    assert repo.query.all().total == 0
    order = Order(customer_id="c1", total=100.0)
    repo.add(order)
    assert repo.get(order.id).total == 100.0


def test_second_order_round_trips():
    repo = domain.repository_for(Order)
    assert repo.query.all().total == 0
    order = Order(customer_id="c2", total=250.0)
    repo.add(order)
    assert repo.get(order.id).total == 250.0


# --8<-- [end:tests]
