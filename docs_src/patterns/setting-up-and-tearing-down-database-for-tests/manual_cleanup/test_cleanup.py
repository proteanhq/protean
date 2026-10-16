# --8<-- [start:tests]
from orderdesk import Order, OrderPlaced, domain

# Each pair of tests expects an empty store at the start, so whichever test
# runs second fails if clean_data did not reset that store.


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


# A consumer group reads a stream from its start, so each test uses its own
# group and finds the other test's message unless the broker was reset.
def test_first_message_is_published():
    broker = domain.brokers["default"]
    assert broker.read("orders", "first", 10) == []
    broker.publish("orders", {"order_id": "o1"})
    assert len(broker.read("orders", "first", 10)) == 1


def test_second_message_is_published():
    broker = domain.brokers["default"]
    assert broker.read("orders", "second", 10) == []
    broker.publish("orders", {"order_id": "o2"})
    assert len(broker.read("orders", "second", 10)) == 1


def _place_order(customer_id):
    order = Order(customer_id=customer_id, total=100.0)
    order.raise_(OrderPlaced(order_id=order.id))
    domain.repository_for(Order).add(order)


def test_first_event_is_stored():
    store = domain.event_store.store
    assert list(store.read_all()) == []
    _place_order("c1")
    assert len(list(store.read_all())) == 1


def test_second_event_is_stored():
    store = domain.event_store.store
    assert list(store.read_all()) == []
    _place_order("c2")
    assert len(list(store.read_all())) == 1


# --8<-- [end:tests]
