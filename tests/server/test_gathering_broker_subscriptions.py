import pytest

from protean.core.subscriber import BaseSubscriber
from protean.server import Engine
from protean.utils import fqn


class DummySubscriber(BaseSubscriber):
    def __call__(self, data: dict):
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(DummySubscriber, channel="test_channel")
    test_domain.init(traverse=False)


@pytest.fixture
def engine(test_domain):
    return Engine(test_domain, test_mode=True)


def test_broker_subscriptions(engine):
    assert len(engine._broker_subscriptions) == 1

    assert fqn(DummySubscriber) in engine._broker_subscriptions
