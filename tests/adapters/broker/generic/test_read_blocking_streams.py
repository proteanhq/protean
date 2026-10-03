"""Tests for read_blocking_streams across every configured broker."""

from uuid import uuid4

import pytest


@pytest.mark.basic_pubsub
def test_read_blocking_streams_keys_every_stream_in_order(broker):
    first = f"streams-first-{uuid4().hex}"
    second = f"streams-second-{uuid4().hex}"
    message = {"foo": "bar"}
    broker.publish(second, message)

    result = broker.read_blocking_streams(
        [first, second], "streams-group", "streams-consumer", timeout_ms=0
    )

    assert list(result) == [first, second]
    assert result[first] == []
    assert len(result[second]) == 1
    identifier, payload = result[second][0]
    assert isinstance(identifier, str)
    assert payload == message


@pytest.mark.basic_pubsub
def test_read_blocking_streams_with_no_streams_returns_empty_dict(broker):
    assert broker.read_blocking_streams([], "streams-group", "streams-consumer") == {}
