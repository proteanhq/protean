"""Tests for SQL query latency logging on the SQLAlchemy SQLite adapter.

Verifies that:
- Queries exceeding ``[logging].slow_query_threshold_ms`` produce a WARNING
  on ``protean.adapters.repository.sqlalchemy.slow_query``.
- Queries below the threshold are silent at WARNING but produce a DEBUG
  record on ``protean.adapters.repository.sqlalchemy.query`` when enabled.
- Statements longer than ``slow_query_truncate_chars`` are truncated in log
  records (to avoid dumping megabyte-sized bulk inserts).
- ``correlation_id`` / ``causation_id`` flow onto every record automatically
  when ``ProteanCorrelationFilter`` is installed on the root logger.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

from protean.adapters.repository import sqlalchemy as sqlalchemy_adapter
from protean.integrations.logging import ProteanCorrelationFilter
from protean.utils.eventing import (
    DomainMeta,
    Message,
    MessageHeaders,
    Metadata,
)
from protean.utils.globals import g


SLOW_QUERY_LOGGER = "protean.adapters.repository.sqlalchemy.slow_query"
QUERY_LOGGER = "protean.adapters.repository.sqlalchemy.query"


def _slow_query_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == SLOW_QUERY_LOGGER]


def _query_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == QUERY_LOGGER]


def _run_trivial_query(test_domain) -> None:
    """Execute a trivial query via the SAProvider engine."""
    provider = test_domain.providers["default"]
    with provider._engine.connect() as conn:
        conn.execute(text("SELECT 1"))


@pytest.mark.sqlite
class TestSlowQueryWarningEmitted:
    """Threshold of 0 forces every query to be classified as slow."""

    @pytest.fixture(autouse=True)
    def lower_threshold(self, test_domain):
        test_domain.config["logging"]["slow_query_threshold_ms"] = 0

    def test_slow_query_warning_emitted(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger=SLOW_QUERY_LOGGER):
            _run_trivial_query(test_domain)

        slow = _slow_query_records(caplog)
        assert len(slow) >= 1
        record = slow[0]
        assert record.levelno == logging.WARNING
        assert record.threshold_ms == 0
        assert record.duration_ms > 0
        assert "SELECT 1" in record.statement


@pytest.mark.sqlite
class TestFastQueryNoWarning:
    """A high threshold keeps the slow-query logger silent."""

    @pytest.fixture(autouse=True)
    def raise_threshold(self, test_domain):
        test_domain.config["logging"]["slow_query_threshold_ms"] = 10_000

    def test_fast_query_no_warning(self, test_domain, caplog):
        with caplog.at_level(logging.WARNING, logger=SLOW_QUERY_LOGGER):
            _run_trivial_query(test_domain)

        assert _slow_query_records(caplog) == []


@pytest.mark.sqlite
class TestDebugQueryLogging:
    """Every query emits a DEBUG record on the general query logger."""

    @pytest.fixture(autouse=True)
    def raise_threshold(self, test_domain):
        # Keep threshold high so the event is DEBUG, not WARNING.
        test_domain.config["logging"]["slow_query_threshold_ms"] = 10_000

    def test_debug_query_logging(self, test_domain, caplog):
        with caplog.at_level(logging.DEBUG, logger=QUERY_LOGGER):
            _run_trivial_query(test_domain)

        debug = _query_records(caplog)
        assert len(debug) >= 1
        record = debug[0]
        assert record.levelno == logging.DEBUG
        assert record.threshold_ms == 10_000
        assert record.duration_ms >= 0
        assert "SELECT 1" in record.statement


@pytest.mark.sqlite
class TestStatementTruncation:
    """Large statements are truncated per slow_query_truncate_chars."""

    @pytest.fixture(autouse=True)
    def configure_truncation(self, test_domain):
        test_domain.config["logging"]["slow_query_threshold_ms"] = 0
        test_domain.config["logging"]["slow_query_truncate_chars"] = 100

    def test_statement_truncation(self, test_domain, caplog):
        long_predicate = " OR ".join("1 = 1" for _ in range(400))
        big_sql = f"SELECT 1 WHERE {long_predicate}"
        assert len(big_sql) > 1000  # sanity: statement is long

        with caplog.at_level(logging.DEBUG, logger=SLOW_QUERY_LOGGER):
            provider = test_domain.providers["default"]
            with provider._engine.connect() as conn:
                conn.execute(text(big_sql))

        slow = _slow_query_records(caplog)
        assert len(slow) >= 1
        record = slow[0]
        # Truncated to 100 chars + "..." suffix
        assert record.statement.endswith("...")
        assert len(record.statement) == 100 + len("...")


@pytest.mark.sqlite
class TestSlowQueryIncludesCorrelationId:
    """With the correlation filter installed, records carry correlation_id."""

    @pytest.fixture(autouse=True)
    def install_filter(self, test_domain):
        test_domain.config["logging"]["slow_query_threshold_ms"] = 0
        # The filter is installed on the dedicated slow-query logger so it
        # runs at record emission time. In production ``Domain.configure_logging()``
        # places the same filter on the root logger; caplog intercepts records
        # before that chain, so we attach it here for deterministic assertion.
        slow_logger = logging.getLogger(SLOW_QUERY_LOGGER)
        filt = ProteanCorrelationFilter()
        slow_logger.addFilter(filt)
        try:
            yield
        finally:
            slow_logger.removeFilter(filt)

    def test_slow_query_includes_correlation_id(self, test_domain, caplog):
        msg = Message(
            data={},
            metadata=Metadata(
                headers=MessageHeaders(id="msg-sql", type="Test.Q.v1"),
                domain=DomainMeta(
                    kind="COMMAND",
                    correlation_id="corr-sql-42",
                    causation_id="cause-sql-42",
                ),
            ),
        )
        g.message_in_context = msg
        try:
            with caplog.at_level(logging.DEBUG, logger=SLOW_QUERY_LOGGER):
                _run_trivial_query(test_domain)
        finally:
            g.pop("message_in_context", None)

        slow = _slow_query_records(caplog)
        assert len(slow) >= 1
        assert slow[0].correlation_id == "corr-sql-42"
        assert slow[0].causation_id == "cause-sql-42"


@pytest.mark.sqlite
class TestHelperFunctions:
    """Direct unit tests for small helpers. Marked ``sqlite`` because the test
    module itself imports from the SQLAlchemy adapter and the parent conftest
    boots a SQLite schema; grouping these here keeps all adapter-specific
    coverage in one place."""

    def test_truncate_statement_noop_when_within_limit(self):
        assert sqlalchemy_adapter._truncate_statement("SELECT 1", 100) == "SELECT 1"

    def test_truncate_statement_disabled_with_zero(self):
        long = "x" * 200
        assert sqlalchemy_adapter._truncate_statement(long, 0) == long

    def test_truncate_statement_appends_ellipsis(self):
        truncated = sqlalchemy_adapter._truncate_statement("x" * 200, 10)
        assert truncated == "xxxxxxxxxx..."
