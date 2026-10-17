# --8<-- [start:tests]
from orderdesk import Order, domain


# Each test starts by checking the store is empty, so whichever runs second
# fails if the first test's order leaked into it.
def test_first_order_is_saved():
    repo = domain.repository_for(Order)
    assert repo.query.all().total == 0
    repo.add(Order(customer_id="c1", total=100.0))
    assert repo.query.all().total == 1


def test_second_order_is_saved():
    repo = domain.repository_for(Order)
    assert repo.query.all().total == 0
    repo.add(Order(customer_id="c2", total=250.0))
    assert repo.query.all().total == 1


def test_the_domain_runs_events_and_commands_in_process():
    assert domain.config["event_processing"] == "sync"
    assert domain.config["command_processing"] == "sync"


# --8<-- [end:tests]
