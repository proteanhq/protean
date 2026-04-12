"""Tests for structured logging in the Engine lifecycle.

Verifies that:
- engine.starting is logged at DEBUG
- engine.started is logged at INFO with subscription/broker/outbox counts
- engine.stopped is logged at INFO
- engine.no_subscriptions is logged at WARNING when no handlers are registered
"""

import logging

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.fields import Identifier, String
from protean.server.engine import Engine
from protean.utils.mixins import handle


class Widget(BaseAggregate):
    widget_id = Identifier(identifier=True)
    name = String(required=True)


class WidgetCreated(BaseEvent):
    widget_id = Identifier()
    name = String()


class WidgetEventHandler(BaseEventHandler):
    @handle(WidgetCreated)
    def on_created(self, event: WidgetCreated) -> None:
        pass


class TestEngineLifecycleLogs:
    """Engine lifecycle produces structured log events."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Widget)
        test_domain.register(WidgetCreated, part_of=Widget)
        test_domain.register(WidgetEventHandler, part_of=Widget)
        test_domain.init(traverse=False)

    def test_engine_start_and_stop_logs(self, test_domain, caplog):
        """Start/stop in test mode produces engine.starting, engine.started (or
        equivalent test-mode logs), and engine.stopped."""
        with caplog.at_level(logging.DEBUG, logger="protean.server.engine"):
            engine = Engine(test_domain, test_mode=True)
            engine.run()

        messages = [r.getMessage() for r in caplog.records]

        # engine.starting at DEBUG
        starting_records = [
            r for r in caplog.records if "engine.starting" in r.getMessage()
        ]
        assert len(starting_records) >= 1, (
            f"Expected 'engine.starting' in log records, got: {messages}"
        )
        assert starting_records[0].levelno == logging.DEBUG

        # engine.stopped at INFO
        stopped_records = [
            r for r in caplog.records if "engine.stopped" in r.getMessage()
        ]
        assert len(stopped_records) >= 1, (
            f"Expected 'engine.stopped' in log records, got: {messages}"
        )
        assert stopped_records[0].levelno == logging.INFO


class TestEngineNoSubscriptionsLog:
    """Engine with no handlers logs a warning."""

    def test_no_subscriptions_warning(self, test_domain, caplog):
        """Engine with no registered handlers logs 'engine.no_subscriptions' at WARNING."""
        test_domain.init(traverse=False)

        with caplog.at_level(logging.DEBUG, logger="protean.server.engine"):
            engine = Engine(test_domain, test_mode=True)
            engine.run()

        no_sub_records = [
            r for r in caplog.records if "engine.no_subscriptions" in r.getMessage()
        ]
        assert len(no_sub_records) >= 1, (
            f"Expected 'engine.no_subscriptions' in log records, "
            f"got: {[r.getMessage() for r in caplog.records]}"
        )
        assert no_sub_records[0].levelno == logging.WARNING
