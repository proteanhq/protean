"""Regression tests for #1213 (Redis-specific crash vector).

Re-running ``domain.init()`` in a process that also runs the Engine used to
close the live ``RedisBroker`` — setting ``redis_instance = None`` on the very
instance the Engine's subscription still held. Its next blocking read then hit
``AttributeError: 'NoneType' object has no attribute 'xreadgroup'`` on every
poll tick, halting consumption until the process restarted.
"""

import pytest

from protean.adapters.broker.redis import RedisBroker


@pytest.fixture
def redis_broker(test_domain):
    return test_domain.brokers["default"]


@pytest.mark.redis
def test_reinit_keeps_redis_connection_alive(redis_broker, test_domain):
    assert isinstance(redis_broker, RedisBroker)
    assert redis_broker.redis_instance is not None

    # A scheduler cron tick re-initializing the domain.
    test_domain.init(traverse=False)

    # Same live instance, connection intact — no teardown out from under it.
    assert test_domain.brokers["default"] is redis_broker
    assert redis_broker.redis_instance is not None


@pytest.mark.redis
def test_redis_broker_still_reads_after_reinit(redis_broker, test_domain):
    """The captured reference (as the Engine holds) can still read post-reinit."""
    stream = "reinit_stream"
    consumer_group = "reinit_group"

    redis_broker.publish(stream, {"data": "before-reinit"})

    test_domain.init(traverse=False)

    # This is the call that used to raise AttributeError on None.
    result = redis_broker.get_next(stream, consumer_group)
    assert result is not None
    assert result[1] == {"data": "before-reinit"}
