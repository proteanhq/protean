"""Tests for structured logging in adapter error paths.

Covers the credential redaction in sqlalchemy connection_failed logging
and other adapter error path log behavior that can be tested without
external services.
"""

import logging
from unittest.mock import MagicMock

import pytest


class TestSqlAlchemyCredentialRedaction:
    """The sqlalchemy connection_failed log redacts database credentials."""

    @pytest.mark.no_test_domain
    def test_connection_failed_redacts_password(self, caplog):
        """is_alive() failure logs a redacted URI with password replaced by ***."""
        try:
            from protean.adapters.repository.sqlalchemy import SAProvider
            from sqlalchemy.exc import DatabaseError
        except ImportError:
            pytest.skip("sqlalchemy not installed")

        # Build a mock that passes isinstance checks but has the attrs
        # is_alive() needs — avoids instantiating the abstract class.
        provider = MagicMock(spec=SAProvider)
        provider.conn_info = {
            "database_uri": "postgresql://admin:s3cret@localhost:5432/mydb"
        }

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = DatabaseError("", {}, Exception("conn refused"))
        provider.get_connection = MagicMock(return_value=mock_conn)

        # Call the real is_alive method with our mock as self
        with caplog.at_level(logging.ERROR):
            result = SAProvider.is_alive(provider)

        assert result is False

        error_records = [
            r for r in caplog.records
            if "repository.sqlalchemy.connection_failed" in r.getMessage()
        ]
        assert len(error_records) >= 1, (
            f"Expected 'repository.sqlalchemy.connection_failed' in log records, "
            f"got: {[r.getMessage() for r in caplog.records]}"
        )

        record = error_records[0]
        assert record.exc_info is not None, "exc_info should be populated"

        # Verify password is redacted in the extra field
        assert hasattr(record, "database_uri"), "database_uri should be in extra"
        assert "s3cret" not in record.database_uri, "Password must be redacted"
        assert "***" in record.database_uri, "Password should be replaced with ***"
        assert "admin" in record.database_uri, "Username should be preserved"
        assert "mydb" in record.database_uri, "Database name should be preserved"

    @pytest.mark.no_test_domain
    def test_connection_failed_handles_unparseable_uri(self, caplog):
        """is_alive() failure with an unparseable URI logs '<unparseable>'."""
        try:
            from protean.adapters.repository.sqlalchemy import SAProvider
            from sqlalchemy.exc import DatabaseError
        except ImportError:
            pytest.skip("sqlalchemy not installed")

        provider = MagicMock(spec=SAProvider)
        provider.conn_info = {
            "database_uri": "not-a-valid-uri"
        }

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = DatabaseError("", {}, Exception("conn refused"))
        provider.get_connection = MagicMock(return_value=mock_conn)

        with caplog.at_level(logging.ERROR):
            result = SAProvider.is_alive(provider)

        assert result is False

        error_records = [
            r for r in caplog.records
            if "repository.sqlalchemy.connection_failed" in r.getMessage()
        ]
        assert len(error_records) >= 1

        record = error_records[0]
        assert record.database_uri == "<unparseable>"
