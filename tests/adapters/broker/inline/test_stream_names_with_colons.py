"""The inline broker keys a consumer group by ``{stream}:{group}``. A stream
name can itself hold colons (``test::order``, a partition stream), so the
broker splits the key at its last colon."""

import pytest

STREAM = "test::order"
GROUP = "app.Handler"
DLQ_STREAM = f"{STREAM}:dlq"


@pytest.fixture
def dead_lettered(broker):
    """Publish one message to ``STREAM`` and send it straight to the DLQ."""
    broker._adapter._max_retries = 0
    identifier = broker.publish(STREAM, {"foo": "bar"})
    assert broker.get_next(STREAM, GROUP) is not None
    assert broker.nack(STREAM, identifier, GROUP) is True
    return identifier


def test_consumer_groups_are_keyed_by_group_name(broker):
    broker.publish(STREAM, {"foo": "bar"})
    assert broker.get_next(STREAM, GROUP) is not None

    groups = broker._adapter.consumer_groups()

    assert list(groups) == [GROUP]
    assert groups[GROUP]["name"] == GROUP
    assert groups[GROUP]["pending"] == 1


def test_health_names_the_consumer_group(broker):
    broker.publish(STREAM, {"foo": "bar"})
    assert broker.get_next(STREAM, GROUP) is not None

    assert broker._adapter.health().consumer_groups == {
        "count": 1,
        "names": [GROUP],
    }


def test_get_dlq_messages_for_a_group_keys_by_full_stream(broker, dead_lettered):
    dlq_messages = broker._adapter.get_dlq_messages(GROUP)

    assert list(dlq_messages) == [STREAM]
    assert dlq_messages[STREAM][0][0] == dead_lettered


def test_dlq_list_reports_the_full_stream_and_group(broker, dead_lettered):
    entries = broker.dlq_list([DLQ_STREAM])

    assert len(entries) == 1
    assert entries[0].dlq_id == dead_lettered
    assert entries[0].stream == STREAM
    assert entries[0].consumer_group == GROUP
    assert entries[0].dlq_stream == DLQ_STREAM


def test_dlq_inspect_finds_the_entry(broker, dead_lettered):
    entry = broker.dlq_inspect(DLQ_STREAM, dead_lettered)

    assert entry is not None
    assert entry.stream == STREAM
    assert entry.consumer_group == GROUP


def test_dlq_replay_republishes_the_entry(broker, dead_lettered):
    assert broker.dlq_replay(DLQ_STREAM, dead_lettered, "target") is True

    replayed = broker.get_next("target", GROUP)
    assert replayed is not None
    assert replayed[1] == {"foo": "bar"}


def test_dlq_replay_all_republishes_every_entry(broker, dead_lettered):
    assert broker.dlq_replay_all(DLQ_STREAM, "target") == 1


def test_dlq_purge_removes_every_entry(broker, dead_lettered):
    assert broker.dlq_purge(DLQ_STREAM) == 1
    assert broker.dlq_list([DLQ_STREAM]) == []
