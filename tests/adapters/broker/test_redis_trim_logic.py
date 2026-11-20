"""Core unit tests for RedisBroker.trim() error handling.

trim() runs one Lua script against a live Redis; its trimming rule is tested in
tests/adapters/broker/redis/test_redis_stream_retention.py (marked
``@pytest.mark.redis``). These tests cover the Python side without a running
server. The broker is built with ``object.__new__`` so no connection is made.
"""

import redis

from protean.adapters.broker.redis import RedisBroker


def _broker(script):
    """Build a RedisBroker bypassing __init__, with ``script`` as the trim script."""
    broker = object.__new__(RedisBroker)
    broker.redis_instance = object()
    broker._lua_trim_by_progress = script
    return broker


class TestTrimScriptCall:
    def test_returns_the_scripts_count_and_passes_the_stream(self):
        calls: list[dict] = []

        def script(*, keys, client):
            calls.append({"keys": keys, "client": client})
            return 7

        broker = _broker(script)

        assert broker.trim("orders") == 7
        assert calls == [{"keys": ["orders"], "client": broker.redis_instance}]

    def test_script_error_is_logged_and_returns_zero(self, caplog):
        def script(*, keys, client):
            raise redis.ResponseError("trim failed")

        broker = _broker(script)

        assert broker.trim("orders") == 0
        assert "Failed to trim stream orders: trim failed" in caplog.text
