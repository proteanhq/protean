from protean.adapters.event_store.memory import MemoryMessage


def test_write_to_event_store(test_domain):
    position = test_domain.event_store.store._write(
        "testStream-123", "Event1", {"foo": "bar"}
    )

    assert position == 0

    repo = test_domain.repository_for(MemoryMessage)
    message = repo.get(1)
    assert message.position == 0


def test_that_position_is_incremented(test_domain):
    for i in range(3):
        test_domain.event_store.store._write("testStream-123", "Event1", {"foo": "bar"})

    repo = test_domain.repository_for(MemoryMessage)
    message = repo.get(3)
    assert message.position == 2


def test_multiple_writes_to_event_store(test_domain):
    for i in range(5):
        position = test_domain.event_store.store._write(
            "testStream-123", "Event1", {"foo": f"bar{i}"}
        )

    position = test_domain.event_store.store._write(
        "testStream-123", "Event1", {"foo": "bar"}
    )
    assert position == 5
