"""An outbox processor with ``tick_interval`` 0 keeps polling without a wait.

The outbox backoff has no starting value for a zero wait, so a wait of 0 cannot
double and stays 0 whatever ``max_tick_interval`` says.
"""

from unittest.mock import Mock

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import String
from protean.server.outbox_processor import OutboxProcessor


class Ledger(BaseAggregate):
    name: String(max_length=50)


class MockEngine:
    def __init__(self, domain):
        self.domain = domain
        self.loop = None
        self.emitter = Mock()


@pytest.fixture
def outbox_domain(test_domain):
    test_domain.config["enable_outbox"] = True
    test_domain.config["server"]["default_subscription_type"] = "stream"
    test_domain.register(Ledger)
    test_domain.init(traverse=False)
    return test_domain


@pytest.mark.database
@pytest.mark.asyncio
async def test_zero_tick_interval_stays_zero_on_empty_polls(outbox_domain):
    processor = OutboxProcessor(
        MockEngine(outbox_domain),
        "default",
        "default",
        tick_interval=0,
        max_tick_interval=5,
    )
    await processor.initialize()

    waits = []
    for _ in range(4):
        assert await processor.tick() is False
        waits.append(processor.tick_interval)

    assert waits == [0, 0, 0, 0]
    assert processor.max_tick_interval == 5.0
