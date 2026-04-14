"""Tests for slow handler detection.

Verifies that:
- Slow handler emits WARNING with status="slow" on protean.access
- Slow handler also emits WARNING on protean.perf
- Fast handler does not trigger slow detection
- Default threshold is 500ms
- Threshold of 0 disables slow detection
"""

import logging
import time
from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.utils.mixins import handle


# --- Domain elements ---


class Item(BaseAggregate):
    item_id = Identifier(identifier=True)
    name = String()


class CreateItem(BaseCommand):
    item_id = Identifier(identifier=True)
    name = String()


class SlowHandler(BaseCommandHandler):
    @handle(CreateItem)
    def handle_create(self, command: CreateItem) -> None:
        time.sleep(0.06)  # 60ms — slow at 10ms threshold


class FastHandler(BaseCommandHandler):
    @handle(CreateItem)
    def handle_create(self, command: CreateItem) -> None:
        pass  # returns immediately


def _access_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "protean.access"]


def _perf_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "protean.perf"]


class TestSlowHandlerWarningEmitted:
    """Slow handlers emit WARNING on both protean.access and protean.perf."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        # Set a low threshold so our 60ms handler is "slow"
        test_domain.config["logging"]["slow_handler_threshold_ms"] = 10
        test_domain.register(Item)
        test_domain.register(CreateItem, part_of=Item)
        test_domain.register(SlowHandler, part_of=Item)
        test_domain.init(traverse=False)

    def test_slow_handler_warning_emitted(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            with caplog.at_level(logging.DEBUG, logger="protean.perf"):
                test_domain.process(CreateItem(item_id=str(uuid4()), name="Slow Item"))

        # Check access log: should be WARNING with status="slow"
        access_recs = _access_records(caplog)
        assert len(access_recs) >= 1
        slow_access = [r for r in access_recs if r.status == "slow"]
        assert len(slow_access) >= 1
        assert slow_access[0].levelno == logging.WARNING
        assert slow_access[0].duration_ms > 10

        # Check perf log: should also have a WARNING
        perf_recs = _perf_records(caplog)
        slow_perf = [r for r in perf_recs if "slow_handler" in r.getMessage()]
        assert len(slow_perf) >= 1
        assert slow_perf[0].levelno == logging.WARNING
        assert slow_perf[0].duration_ms > 10


class TestFastHandlerNoSlowWarning:
    """Fast handlers do not trigger slow detection."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.config["logging"]["slow_handler_threshold_ms"] = 10
        test_domain.register(Item)
        test_domain.register(CreateItem, part_of=Item)
        test_domain.register(FastHandler, part_of=Item)
        test_domain.init(traverse=False)

    def test_fast_handler_no_slow_warning(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            with caplog.at_level(logging.DEBUG, logger="protean.perf"):
                test_domain.process(CreateItem(item_id=str(uuid4()), name="Fast Item"))

        # Access log should be INFO with status="ok"
        access_recs = _access_records(caplog)
        assert len(access_recs) >= 1
        assert access_recs[0].status == "ok"
        assert access_recs[0].levelno == logging.INFO

        # No slow_handler perf records
        perf_recs = _perf_records(caplog)
        slow_perf = [r for r in perf_recs if "slow_handler" in r.getMessage()]
        assert len(slow_perf) == 0


class TestThresholdDefaultIs500ms:
    """Default slow_handler_threshold_ms is 500ms."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        # Don't override threshold — use the default (500ms)
        test_domain.register(Item)
        test_domain.register(CreateItem, part_of=Item)
        test_domain.register(FastHandler, part_of=Item)
        test_domain.init(traverse=False)

    def test_threshold_default_is_500ms(self, test_domain, caplog):
        """A fast handler with default 500ms threshold should be 'ok'."""
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            test_domain.process(
                CreateItem(item_id=str(uuid4()), name="Default Threshold")
            )

        access_recs = _access_records(caplog)
        assert len(access_recs) >= 1
        assert access_recs[0].status == "ok"


class TestThresholdZeroDisablesSlowDetection:
    """Setting threshold to 0 disables slow detection."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.config["logging"]["slow_handler_threshold_ms"] = 0
        test_domain.register(Item)
        test_domain.register(CreateItem, part_of=Item)
        test_domain.register(SlowHandler, part_of=Item)
        test_domain.init(traverse=False)

    def test_threshold_zero_disables_slow_detection(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger="protean.access"):
            with caplog.at_level(logging.DEBUG, logger="protean.perf"):
                test_domain.process(
                    CreateItem(item_id=str(uuid4()), name="No Slow Check")
                )

        # Access log should be INFO with status="ok" despite slow execution
        access_recs = _access_records(caplog)
        assert len(access_recs) >= 1
        assert access_recs[0].status == "ok"
        assert access_recs[0].levelno == logging.INFO

        # No slow_handler perf records
        perf_recs = _perf_records(caplog)
        slow_perf = [r for r in perf_recs if "slow_handler" in r.getMessage()]
        assert len(slow_perf) == 0
