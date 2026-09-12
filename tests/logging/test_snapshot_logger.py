"""The ``protean.snapshot`` logger and its wide-event helper."""

import logging

import pytest

from protean.integrations.logging import SNAPSHOT_EVENT_DISCARDED, log_snapshot_event


@pytest.mark.no_test_domain
def test_framework_logger_registered_at_warning():
    from protean.utils.logging import _FRAMEWORK_LOGGERS_NORMAL

    assert _FRAMEWORK_LOGGERS_NORMAL.get("protean.snapshot") == logging.WARNING


@pytest.mark.no_test_domain
def test_log_snapshot_event_emits_warning_with_fields(caplog):
    with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
        log_snapshot_event(
            SNAPSHOT_EVENT_DISCARDED,
            aggregate="User",
            aggregate_id="user-1",
            reason="extra fields not permitted",
        )

    records = [r for r in caplog.records if r.name == "protean.snapshot"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.WARNING
    assert record.getMessage() == "snapshot_discarded"
    assert record.aggregate == "User"
    assert record.aggregate_id == "user-1"
    assert record.reason == "extra fields not permitted"


@pytest.mark.no_test_domain
def test_log_snapshot_event_drops_reserved_logrecord_keys(caplog):
    """A field colliding with a stdlib ``LogRecord`` attribute is dropped rather
    than raising when the record is constructed."""
    with caplog.at_level(logging.WARNING, logger="protean.snapshot"):
        log_snapshot_event(SNAPSHOT_EVENT_DISCARDED, aggregate="User", name="collision")

    records = [r for r in caplog.records if r.name == "protean.snapshot"]
    assert len(records) == 1
    # ``name`` is the logger name on a LogRecord, untouched by the dropped field.
    assert records[0].name == "protean.snapshot"
