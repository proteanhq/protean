"""Tests for the logging snapshot that isolates each test's logging setup."""

import logging
from uuid import uuid4

import pytest
import structlog

from tests.logging_isolation import LoggingSnapshot

pytestmark = pytest.mark.no_test_domain


def _name() -> str:
    return f"tests.logging_isolation.{uuid4().hex}"


def test_a_level_set_on_an_existing_logger_is_put_back():
    logger = logging.getLogger(_name())
    logger.setLevel(logging.INFO)
    snapshot = LoggingSnapshot.take()

    logger.setLevel(logging.ERROR)
    snapshot.restore()

    assert logger.level == logging.INFO


def test_a_logger_created_during_the_test_gets_the_defaults():
    snapshot = LoggingSnapshot.take()

    logger = logging.getLogger(_name())
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    logger.addHandler(logging.StreamHandler())
    snapshot.restore()

    assert logger.level == logging.NOTSET
    assert logger.propagate is True
    assert logger.handlers == []


def test_a_new_logger_keeps_the_null_handler_a_library_adds_on_import():
    snapshot = LoggingSnapshot.take()

    logger = logging.getLogger(_name())
    null_handler = logging.NullHandler()
    logger.addHandler(null_handler)
    snapshot.restore()

    assert logger.handlers == [null_handler]


def test_a_file_handler_left_behind_is_closed(tmp_path):
    snapshot = LoggingSnapshot.take()

    handler = logging.FileHandler(tmp_path / "app.log")
    logging.getLogger().addHandler(handler)
    snapshot.restore()

    assert handler not in logging.getLogger().handlers
    assert handler.stream is None


def test_a_handler_attached_before_the_snapshot_stays_open(tmp_path):
    logger = logging.getLogger(_name())
    handler = logging.FileHandler(tmp_path / "app.log")
    logger.addHandler(handler)
    try:
        snapshot = LoggingSnapshot.take()
        logger.removeHandler(handler)
        snapshot.restore()

        assert logger.handlers == [handler]
        assert handler.stream is not None
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_an_in_place_change_to_the_structlog_processors_is_undone():
    processors = structlog.get_config()["processors"]
    before = list(processors)
    snapshot = LoggingSnapshot.take()

    processors.append(lambda logger, method, event: event)
    snapshot.restore()

    assert structlog.get_config()["processors"] == before


def test_logging_disable_is_put_back():
    snapshot = LoggingSnapshot.take()

    logging.disable(logging.CRITICAL)
    snapshot.restore()

    assert logging.Logger.manager.disable == logging.NOTSET
