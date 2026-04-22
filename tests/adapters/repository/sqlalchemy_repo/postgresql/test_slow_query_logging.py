"""PostgreSQL smoke test for SQL query latency logging.

Verifies that the ``before_cursor_execute`` / ``after_cursor_execute``
event listeners attach to the PostgreSQL engine and emit slow-query
WARNING records like the SQLite path. The exhaustive behaviour (DEBUG
logging, truncation, correlation) is covered by the SQLite tests in
``sqlite/test_slow_query_logging.py``.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text


SLOW_QUERY_LOGGER = "protean.adapters.repository.sqlalchemy.slow_query"


@pytest.mark.postgresql
class TestSlowQueryWarningEmittedPostgres:
    @pytest.fixture(autouse=True)
    def lower_threshold(self, test_domain):
        test_domain.config["logging"]["slow_query_threshold_ms"] = 0

    def test_slow_query_warning_emitted_postgres(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger=SLOW_QUERY_LOGGER):
            provider = test_domain.providers["default"]
            with provider._engine.connect() as conn:
                conn.execute(text("SELECT 1"))

        slow = [r for r in caplog.records if r.name == SLOW_QUERY_LOGGER]
        assert len(slow) >= 1
        record = slow[0]
        assert record.levelno == logging.WARNING
        assert record.threshold_ms == 0
        assert record.duration_ms > 0
        assert "SELECT 1" in record.statement
