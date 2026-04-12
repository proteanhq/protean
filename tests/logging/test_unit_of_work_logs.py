"""Tests for structured logging in UnitOfWork.

Verifies that:
- ValueError during commit produces ERROR with exc_info and event name "uow.commit_failed"
- General exception during commit produces ERROR with exc_info and "uow.commit_failed"
- Rollback failure produces ERROR with exc_info and event name "uow.rollback_failed"
"""

import logging
from unittest.mock import MagicMock

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError, TransactionError
from protean.fields import Identifier, String


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    name = String(required=True)


class TestUoWCommitFailedLogs:
    """Commit failures produce structured log records with exc_info."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.init(traverse=False)

    def test_commit_value_error_logs_with_exc_info(self, test_domain, caplog):
        """A ValueError during commit logs 'uow.commit_failed' at ERROR with exc_info."""
        with caplog.at_level(logging.DEBUG, logger="protean.core.unit_of_work"):
            uow = UnitOfWork()
            uow.start()

            # Add a session that will raise ValueError on commit
            # (simulates a version conflict from the event store)
            mock_session = MagicMock()
            mock_session.commit.side_effect = ValueError(
                "P0001-ERROR:  expected version conflict"
            )
            uow._sessions["default"] = mock_session

            with pytest.raises(ExpectedVersionError):
                uow.commit()

        commit_failed_records = [
            r for r in caplog.records if "uow.commit_failed" in r.getMessage()
        ]
        assert len(commit_failed_records) >= 1, (
            f"Expected at least one 'uow.commit_failed' record, "
            f"got records: {[r.getMessage() for r in caplog.records]}"
        )
        record = commit_failed_records[0]
        assert record.levelname == "ERROR"
        assert record.exc_info is not None, "exc_info must be populated for stack trace"

    def test_commit_general_exception_logs_with_exc_info(self, test_domain, caplog):
        """A general exception during commit logs 'uow.commit_failed' at ERROR."""
        with caplog.at_level(logging.DEBUG, logger="protean.core.unit_of_work"):
            uow = UnitOfWork()
            uow.start()

            mock_session = MagicMock()
            mock_session.commit.side_effect = RuntimeError("connection lost")
            uow._sessions["default"] = mock_session

            with pytest.raises(TransactionError):
                uow.commit()

        commit_failed_records = [
            r for r in caplog.records if "uow.commit_failed" in r.getMessage()
        ]
        assert len(commit_failed_records) >= 1, (
            f"Expected at least one 'uow.commit_failed' record, "
            f"got records: {[r.getMessage() for r in caplog.records]}"
        )
        record = commit_failed_records[0]
        assert record.levelname == "ERROR"
        assert record.exc_info is not None, "exc_info must be populated for stack trace"


class TestUoWRollbackFailedLogs:
    """Rollback failures produce structured log records with exc_info."""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Account)
        test_domain.init(traverse=False)

    def test_rollback_failure_logs_with_exc_info(self, test_domain, caplog):
        """A rollback failure logs 'uow.rollback_failed' at ERROR with exc_info."""
        with caplog.at_level(logging.DEBUG, logger="protean.core.unit_of_work"):
            uow = UnitOfWork()
            uow.start()

            # Mock a session that fails on rollback
            mock_session = MagicMock()
            mock_session.rollback.side_effect = RuntimeError("rollback connection lost")
            uow._sessions["default"] = mock_session

            uow.rollback()

        rollback_failed_records = [
            r for r in caplog.records if "uow.rollback_failed" in r.getMessage()
        ]
        assert len(rollback_failed_records) >= 1, (
            f"Expected at least one 'uow.rollback_failed' record, "
            f"got records: {[r.getMessage() for r in caplog.records]}"
        )
        record = rollback_failed_records[0]
        assert record.levelname == "ERROR"
        assert record.exc_info is not None, "exc_info must be populated for stack trace"
