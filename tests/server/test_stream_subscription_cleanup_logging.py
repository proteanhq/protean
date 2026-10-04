"""A failed stale-consumer cleanup is logged and does not stop startup."""

import logging

import pytest

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier
from protean.server.engine import Engine
from protean.server.subscription.stream_subscription import StreamSubscription

LOGGER = "protean.server.subscription.stream_subscription"


class CleanupAggregate(BaseAggregate):
    item_id = Identifier()


class CleanupEvent(BaseEvent):
    item_id = Identifier()


class CleanupHandler(BaseEventHandler):
    @handle(CleanupEvent)
    def on_event(self, event: CleanupEvent) -> None:
        pass


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(CleanupAggregate)
    test_domain.register(CleanupEvent, part_of=CleanupAggregate)
    test_domain.register(CleanupHandler, part_of=CleanupAggregate)
    test_domain.init(traverse=False)


def _subscription(test_domain, lanes_enabled: bool = False) -> StreamSubscription:
    if lanes_enabled:
        test_domain.config["server"]["priority_lanes"] = {
            "enabled": True,
            "backfill_suffix": "backfill",
        }
    return StreamSubscription(
        engine=Engine(test_domain, test_mode=True),
        stream_category="cleanup_stream",
        handler=CleanupHandler,
    )


def _fail_cleanup(test_domain, monkeypatch) -> list[str]:
    """Make the broker's stale-consumer cleanup raise; return the streams tried."""
    attempted: list[str] = []

    def _raise(stream, consumer_group, subscription_id):
        attempted.append(stream)
        raise ConnectionError("redis down")

    monkeypatch.setattr(
        test_domain.brokers["default"], "_cleanup_stale_consumers", _raise
    )
    return attempted


def _cleanup_warnings(caplog) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == LOGGER and r.getMessage().startswith("Failed to clean up")
    ]


async def test_primary_cleanup_failure_is_logged_and_startup_continues(
    test_domain, monkeypatch, caplog
):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    attempted = _fail_cleanup(test_domain, monkeypatch)
    subscription = _subscription(test_domain)

    await subscription.initialize()

    assert attempted == ["cleanup_stream"]
    assert subscription.broker is test_domain.brokers["default"]
    records = _cleanup_warnings(caplog)
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert records[0].getMessage() == (
        f"Failed to clean up stale consumers for "
        f"{subscription.subscriber_name} on 'cleanup_stream'"
    )
    assert str(records[0].exc_info[1]) == "redis down"


async def test_backfill_cleanup_failure_is_logged(test_domain, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    attempted = _fail_cleanup(test_domain, monkeypatch)
    subscription = _subscription(test_domain, lanes_enabled=True)

    await subscription.initialize()

    assert attempted == ["cleanup_stream", subscription.backfill_stream]
    prefix = f"Failed to clean up stale consumers for {subscription.subscriber_name}"
    messages = [r.getMessage() for r in _cleanup_warnings(caplog)]
    assert messages == [
        f"{prefix} on 'cleanup_stream'",
        f"{prefix} on '{subscription.backfill_stream}'",
    ]


async def test_no_warning_when_cleanup_succeeds(test_domain, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    subscription = _subscription(test_domain, lanes_enabled=True)

    await subscription.initialize()

    assert _cleanup_warnings(caplog) == []
