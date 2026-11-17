"""Each built-in broker names its technology in ``broker_type``."""

import pytest

from protean.adapters.broker.inline import InlineBroker
from protean.adapters.broker.redis import RedisBroker
from protean.adapters.broker.redis_pubsub import RedisPubSubBroker


@pytest.mark.parametrize(
    "broker_cls, broker_type",
    [
        (InlineBroker, "inline"),
        (RedisBroker, "redis"),
        (RedisPubSubBroker, "redis_pubsub"),
    ],
)
def test_broker_type(broker_cls, broker_type):
    assert broker_cls.broker_type == broker_type


@pytest.mark.parametrize("broker_cls", [InlineBroker, RedisBroker, RedisPubSubBroker])
def test_no_broker_keeps_the_old_attribute(broker_cls):
    assert not hasattr(broker_cls, "__broker__")
