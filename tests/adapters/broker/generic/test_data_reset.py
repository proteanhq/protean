import pytest


@pytest.mark.broker
def test_data_reset(broker):
    broker.publish("test_stream1", {"foo": "bar1"})
    broker.publish("test_stream2", {"foo": "bar2"})

    # Reset broker data
    broker._data_reset()

    # Check that we cannot get messages anymore
    assert broker.get_next("test_stream1", "test_consumer_group") is None
    assert broker.get_next("test_stream2", "test_consumer_group") is None
