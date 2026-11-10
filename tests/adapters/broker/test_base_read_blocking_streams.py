"""Core tests for BaseBroker.read_blocking_streams and its default
``_read_blocking_streams``, using a minimal broker that records its reads.

The default reads every stream but the last without waiting, and waits on the
last stream only when the others are empty. The ``Broker`` service wraps the
call and retries it once after a connection error. No server is needed.
"""

import pytest

from protean.infra.broker import Broker
from protean.port.broker import BaseBroker, BrokerCapabilities

pytestmark = pytest.mark.no_test_domain


class _RecordingBroker(BaseBroker):
    """Implements only what the read paths need, and records every read."""

    blocking = True

    def __init__(self, messages=None, errors=None):
        # Skip BaseBroker.__init__: no domain or connection is needed here.
        self.messages = messages or {}
        self.errors = list(errors or [])
        self.blocking_calls: list[tuple[str, int, int]] = []
        self.read_calls: list[tuple[str, int]] = []
        self.reconnects = 0

    @property
    def capabilities(self):
        if self.blocking:
            return BrokerCapabilities.BLOCKING_READ
        return BrokerCapabilities(0)

    def _read_blocking(
        self, stream, consumer_group, consumer_name, timeout_ms=5000, count=1
    ):
        self.blocking_calls.append((stream, timeout_ms, count))
        if self.errors:
            raise self.errors.pop(0)
        return self.messages.get(stream, [])

    def read(self, stream, consumer_group, limit, *, new_messages=False):
        self.read_calls.append((stream, limit))
        return self.messages.get(stream, [])

    def reconnect(self):
        self.reconnects += 1
        return True

    # Abstract methods the read paths never call
    def _dlq_list(self, dlq_streams, limit):  # pragma: no cover
        raise NotImplementedError

    def _dlq_inspect(self, dlq_stream, dlq_id):  # pragma: no cover
        raise NotImplementedError

    def _dlq_replay(self, dlq_stream, dlq_id, target_stream):  # pragma: no cover
        raise NotImplementedError

    def _dlq_replay_all(self, dlq_stream, target_stream):  # pragma: no cover
        raise NotImplementedError

    def _dlq_purge(self, dlq_stream):  # pragma: no cover
        raise NotImplementedError


MESSAGE = ("1-0", {"n": 1})


class TestDefaultReadBlockingStreams:
    def test_first_stream_with_messages_ends_the_read(self):
        broker = _RecordingBroker(messages={"primary": [MESSAGE]})

        result = broker.read_blocking_streams(
            ["primary", "backfill"], "group", "consumer", timeout_ms=750, count=3
        )

        assert result == {"primary": [MESSAGE], "backfill": []}
        assert list(result) == ["primary", "backfill"]
        assert broker.blocking_calls == [("primary", 0, 3)]

    def test_empty_first_stream_waits_on_the_last(self):
        broker = _RecordingBroker(messages={"backfill": [MESSAGE]})

        result = broker.read_blocking_streams(
            ["primary", "backfill"], "group", "consumer", timeout_ms=750, count=3
        )

        assert result == {"primary": [], "backfill": [MESSAGE]}
        assert list(result) == ["primary", "backfill"]
        assert broker.blocking_calls == [("primary", 0, 3), ("backfill", 750, 3)]

    def test_all_streams_empty_returns_an_empty_list_per_stream(self):
        broker = _RecordingBroker()

        result = broker.read_blocking_streams(
            ["a", "b", "c"], "group", "consumer", timeout_ms=200
        )

        assert result == {"a": [], "b": [], "c": []}
        assert broker.blocking_calls == [("a", 0, 1), ("b", 0, 1), ("c", 200, 1)]

    def test_none_from_read_blocking_becomes_an_empty_list(self):
        broker = _RecordingBroker(messages={"primary": None, "backfill": None})

        result = broker.read_blocking_streams(["primary", "backfill"], "g", "c")

        assert result == {"primary": [], "backfill": []}

    def test_default_with_no_streams_reads_nothing(self):
        broker = _RecordingBroker()

        assert broker._read_blocking_streams([], "group", "consumer") == {}
        assert broker.blocking_calls == []


class TestReadBlockingStreamsWrapper:
    def test_no_streams_returns_empty_dict_without_reading(self):
        broker = _RecordingBroker()

        assert broker.read_blocking_streams([], "group", "consumer") == {}
        assert broker.blocking_calls == []
        assert broker.read_calls == []

    def test_without_blocking_read_falls_back_to_read_per_stream(self):
        broker = _RecordingBroker(messages={"backfill": [MESSAGE]})
        broker.blocking = False

        result = broker.read_blocking_streams(
            ["primary", "backfill"], "group", "consumer", count=4
        )

        assert result == {"primary": [], "backfill": [MESSAGE]}
        assert list(result) == ["primary", "backfill"]
        assert broker.read_calls == [("primary", 4), ("backfill", 4)]
        assert broker.blocking_calls == []

    def test_connection_error_reconnects_and_retries_once(self):
        adapter = _RecordingBroker(
            messages={"primary": [MESSAGE]},
            errors=[ConnectionError("connection gone")],
        )

        result = Broker(adapter).read_blocking_streams(
            ["primary", "backfill"], "g", "c", timeout_ms=750, count=3
        )

        assert result == {"primary": [MESSAGE], "backfill": []}
        assert adapter.reconnects == 1
        # The retry repeats the read with the same timeout and count.
        assert adapter.blocking_calls == [("primary", 0, 3), ("primary", 0, 3)]

    def test_connection_error_is_raised_when_reconnect_fails(self):
        adapter = _RecordingBroker(errors=[ConnectionError("connection gone")])
        adapter.reconnect = lambda: False

        with pytest.raises(ConnectionError):
            Broker(adapter).read_blocking_streams(["primary", "backfill"], "g", "c")

    def test_other_errors_are_raised_without_retry(self):
        adapter = _RecordingBroker(errors=[ValueError("bad")])

        with pytest.raises(ValueError):
            Broker(adapter).read_blocking_streams(["primary", "backfill"], "g", "c")

        assert adapter.reconnects == 0
        assert len(adapter.blocking_calls) == 1
