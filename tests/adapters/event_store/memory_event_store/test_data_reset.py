def test_write_to_event_store(test_domain):
    test_domain.event_store.store._write(
        "testStream-123", "Event1", {"foo": "bar"}, {"kind": "EVENT"}
    )
    assert len(test_domain.event_store.store._read("testStream-123")) == 1

    test_domain.event_store.store._data_reset()
    assert len(test_domain.event_store.store._read("testStream-123")) == 0
