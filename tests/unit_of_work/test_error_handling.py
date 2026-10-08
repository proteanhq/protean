from unittest.mock import MagicMock, Mock, patch

import pytest

from protean import UnitOfWork
from protean.exceptions import (
    ConfigurationError,
    InvalidOperationError,
    TransactionError,
)

from .elements import Person, PersonRepository


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonRepository, part_of=Person)
    test_domain.init(traverse=False)


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestUnitOfWorkErrorHandling:
    """Test error handling scenarios in UnitOfWork"""

    def test_configuration_error_during_commit_is_propagated(self, test_domain):
        """Test that ConfigurationError during commit is re-raised"""
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        # Use pytest.raises to check the exception is propagated correctly
        with pytest.raises(ConfigurationError, match="Configuration issue"):
            with UnitOfWork() as uow:
                repo = test_domain.repository_for(Person)
                person = Person(first_name="Jane", last_name="Doe")
                repo.add(person)

                # Mock session.commit to raise ConfigurationError
                for session in uow._sessions.values():
                    session.commit = Mock(
                        side_effect=ConfigurationError("Configuration issue")
                    )

    def test_general_exception_during_commit_raises_transaction_error(
        self, test_domain
    ):
        """Test that general exceptions during commit are wrapped in TransactionError"""
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        with pytest.raises(TransactionError) as exc_info, UnitOfWork() as uow:
            repo = test_domain.repository_for(Person)
            person = Person(first_name="Jane", last_name="Doe")
            repo.add(person)

            # Mock session.commit to raise a general exception
            for session in uow._sessions.values():
                session.commit = Mock(
                    side_effect=RuntimeError("Database connection failed")
                )

        # Check the error message and extra_info
        assert "Unit of Work commit failed" in str(exc_info.value)
        assert "Database connection failed" in str(exc_info.value)
        assert exc_info.value.extra_info is not None
        assert exc_info.value.extra_info["original_exception"] == "RuntimeError"
        assert (
            exc_info.value.extra_info["original_message"]
            == "Database connection failed"
        )

    def test_p0001_value_error_from_session_commit_raises_transaction_error(
        self, test_domain
    ):
        """Only the Message DB adapter reports a P0001 conflict; the commit does not guess one"""
        raw = "P0001-ERROR:  Wrong expected version: 5 (Stream: s, Stream Version: 0)"
        with pytest.raises(TransactionError) as exc_info:
            with UnitOfWork() as uow:
                repo = test_domain.repository_for(Person)
                repo.add(Person(first_name="Jane", last_name="Doe"))

                for session in uow._sessions.values():
                    session.commit = Mock(side_effect=ValueError(raw))

        assert exc_info.value.extra_info["original_exception"] == "ValueError"
        assert isinstance(exc_info.value.__cause__, ValueError)

    def test_value_error_without_p0001_prefix_raises_transaction_error(
        self, test_domain
    ):
        """A ValueError raised during commit is a failed commit"""
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        with pytest.raises(TransactionError) as exc_info:
            with UnitOfWork() as uow:
                repo = test_domain.repository_for(Person)
                person = Person(first_name="Jane", last_name="Doe")
                repo.add(person)

                for session in uow._sessions.values():
                    session.commit = Mock(side_effect=ValueError("boom"))

        assert exc_info.value.extra_info["original_exception"] == "ValueError"
        assert exc_info.value.extra_info["original_message"] == "boom"
        assert isinstance(exc_info.value.__cause__, ValueError)

    def test_exception_during_rollback_is_logged_but_not_raised(self, test_domain):
        """Test that exceptions during rollback are logged but don't prevent cleanup"""
        uow = UnitOfWork()
        uow.start()

        # Get a session to trigger _sessions population
        session = uow.get_session("default")

        # Mock session.rollback to raise an exception
        session.rollback = Mock(side_effect=RuntimeError("Rollback failed"))

        with patch("protean.core.unit_of_work.logger") as mock_logger:
            # This should not raise an exception, just log the error
            uow.rollback()

            # Check that error was logged via logger.exception
            mock_logger.exception.assert_called_once()
            assert "uow.rollback_failed" in str(mock_logger.exception.call_args)

    def test_session_initialization_when_not_active(self, test_domain):
        """Test session initialization when session is not active"""
        uow = UnitOfWork()
        uow.start()

        provider_name = "default"

        # Mock the provider and session
        mock_session = MagicMock()
        mock_session.is_active = False  # This will trigger the begin() call
        mock_session.begin = Mock()

        with patch.object(uow, "_get_session", return_value=mock_session):
            session = uow._initialize_session(provider_name)

            # Verify session.begin() was called since is_active was False
            mock_session.begin.assert_called_once()
            assert session == mock_session

    def test_session_initialization_when_already_active(self, test_domain):
        """Test session initialization when session is already active"""
        uow = UnitOfWork()
        uow.start()

        provider_name = "default"

        # Mock the provider and session
        mock_session = MagicMock()
        mock_session.is_active = True  # This will skip the begin() call
        mock_session.begin = Mock()

        with patch.object(uow, "_get_session", return_value=mock_session):
            session = uow._initialize_session(provider_name)

            # Verify session.begin() was NOT called since is_active was True
            mock_session.begin.assert_not_called()
            assert session == mock_session

    def test_rollback_when_uow_not_in_progress_raises_error(self, test_domain):
        """Test that rolling back when UoW is not active raises InvalidOperationError"""
        uow = UnitOfWork()

        with pytest.raises(
            InvalidOperationError, match="UnitOfWork is not in progress"
        ):
            uow.rollback()

    def test_commit_when_uow_not_in_progress_raises_error(self, test_domain):
        """Test that committing when UoW is not active raises InvalidOperationError"""
        uow = UnitOfWork()

        with pytest.raises(
            InvalidOperationError, match="UnitOfWork is not in progress"
        ):
            uow.commit()
