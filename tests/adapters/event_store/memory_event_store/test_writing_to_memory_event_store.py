def test_write_to_event_store(test_domain):
    position = test_domain.event_store.store._write(
        "testStream-123", "Event1", {"foo": "bar"}, {"kind": "EVENT"}
    )

    assert position == 0


def test_multiple_writes_to_event_store(test_domain):
    for i in range(5):
        position = test_domain.event_store.store._write(
            "testStream-123", "Event1", {"foo": f"bar{i}"}, {"kind": "EVENT"}
        )

    position = test_domain.event_store.store._write(
        "testStream-123", "Event1", {"foo": "bar"}, {"kind": "EVENT"}
    )
    assert position == 5
