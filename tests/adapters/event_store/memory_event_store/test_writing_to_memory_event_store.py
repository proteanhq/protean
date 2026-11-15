import pytest

from protean.exceptions import ValidationError


def test_write_to_event_store(test_domain):
    position = test_domain.event_store.store.write_message(
        "testStream-123", "Event1", {"foo": "bar"}
    )

    assert position == 0

    messages = test_domain.event_store.store.get_stream_messages("testStream-123")
    assert [(m["global_position"], m["position"]) for m in messages] == [(1, 0)]


def test_that_position_is_incremented(test_domain):
    for _i in range(3):
        test_domain.event_store.store.write_message(
            "testStream-123", "Event1", {"foo": "bar"}
        )

    messages = test_domain.event_store.store.get_stream_messages("testStream-123")
    assert [(m["global_position"], m["position"]) for m in messages] == [
        (1, 0),
        (2, 1),
        (3, 2),
    ]


def test_multiple_writes_to_event_store(test_domain):
    for i in range(5):
        position = test_domain.event_store.store.write_message(
            "testStream-123", "Event1", {"foo": f"bar{i}"}
        )

    position = test_domain.event_store.store.write_message(
        "testStream-123", "Event1", {"foo": "bar"}
    )
    assert position == 5


def test_a_write_with_rejected_metadata_leaves_the_stream_unchanged(test_domain):
    store = test_domain.event_store.store
    store.write_message("testStream-123", "Event1", {"foo": "bar"})

    # Metadata without headers fails validation while the row is built.
    with pytest.raises(ValidationError):
        store.write_message("testStream-123", "Event1", {"foo": "baz"}, metadata={})

    assert [m["data"] for m in store.get_stream_messages("testStream-123")] == [
        {"foo": "bar"}
    ]
    assert store.write_message("testStream-123", "Event1", {"foo": "qux"}) == 1
