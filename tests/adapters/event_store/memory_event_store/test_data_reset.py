def test_write_to_event_store(test_domain):
    test_domain.event_store.store._write(
        "testStream-123",
        "Event1",
        {"foo": "bar"},
        {
            "domain": {"kind": "EVENT"},
            "headers": {
                "id": "test-event-1",
                "type": "Event1",
                "stream": "testStream-123",
            },
        },
    )
    assert len(test_domain.event_store.store._read("testStream-123")) == 1

    test_domain.event_store.store._data_reset()
    assert len(test_domain.event_store.store._read("testStream-123")) == 0
