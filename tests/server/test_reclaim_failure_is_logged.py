"""A failed claim of idle pending messages is logged and does not stop startup."""

import logging

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.subscriber import BaseSubscriber
from protean.fields import Identifier
from protean.server.engine import Engine
from protean.server.subscription.broker_subscription import BrokerSubscription
from protean.server.subscription.stream_subscription import StreamSubscription


class Parcel(BaseAggregate):
    parcel_id = Identifier()


class ParcelSent(BaseEvent):
    parcel_id = Identifier()


class ParcelHandler(BaseEventHandler):
    @handle(ParcelSent)
    def on_sent(self, event: ParcelSent) -> None:
        pass


class ParcelSubscriber(BaseSubscriber):
    def __call__(self, data: dict) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Parcel)
    test_domain.register(ParcelSent, part_of=Parcel)
    test_domain.register(ParcelHandler, part_of=Parcel)
    test_domain.register(ParcelSubscriber, stream="parcels")
    test_domain.init(traverse=False)


@pytest.fixture
def attempted(test_domain, monkeypatch) -> list[tuple[str, str | None, int]]:
    """Make the broker's claim raise; return the streams, consumers and
    thresholds it was called with."""
    calls: list[tuple[str, str | None, int]] = []

    def _raise(stream, group_name, consumer_name, min_idle_ms):
        calls.append((stream, consumer_name, min_idle_ms))
        raise ConnectionError("redis down")

    monkeypatch.setattr(test_domain.brokers["default"], "_reclaim_idle_pending", _raise)
    return calls


def _warnings(caplog, logger: str) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == logger and r.levelno == logging.WARNING
    ]


async def test_stream_subscription_logs_each_failed_stream_and_starts(
    test_domain, attempted, caplog
):
    logger = "protean.server.subscription.stream_subscription"
    caplog.set_level(logging.WARNING, logger=logger)
    test_domain.config["server"]["reclaim_idle_seconds"] = 90
    test_domain.config["server"]["priority_lanes"] = {
        "enabled": True,
        "backfill_suffix": "backfill",
    }
    subscription = StreamSubscription(
        engine=Engine(test_domain, test_mode=True),
        stream_category="parcels_stream",
        handler=ParcelHandler,
    )

    await subscription.initialize()

    assert attempted == [
        ("parcels_stream", subscription.consumer_name, 90_000),
        ("parcels_stream:backfill", subscription.consumer_name, 90_000),
    ]
    assert subscription.retry_counts == {}
    assert len(_warnings(caplog, logger)) == 2
    assert all(
        m.startswith("Failed to claim idle pending") for m in _warnings(caplog, logger)
    )


async def test_broker_subscription_logs_the_failure_and_starts(
    test_domain, attempted, caplog
):
    logger = "protean.server.subscription.broker_subscription"
    caplog.set_level(logging.WARNING, logger=logger)
    engine = Engine(test_domain, test_mode=True)
    subscription = BrokerSubscription(
        engine, test_domain.brokers["default"], "parcels", ParcelSubscriber
    )

    await subscription.initialize()

    assert attempted == [("parcels", None, 120_000)]
    assert subscription.retry_counts == {}
    assert len(_warnings(caplog, logger)) == 1
    assert _warnings(caplog, logger)[0].startswith("Failed to claim idle pending")
