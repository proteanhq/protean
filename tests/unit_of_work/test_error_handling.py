import pytest
from unittest.mock import Mock, patch, MagicMock

from protean import UnitOfWork
from protean.exceptions import (
    ConfigurationError,
    TransactionError,
    ExpectedVersionError,
    InvalidOperationError,
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

        with pytest.raises(TransactionError) as exc_info:
            with UnitOfWork() as uow:
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

    def test_expected_version_error_handling_with_p0001_message(self, test_domain):
        """Test ExpectedVersionError handling when ValueError has P0001 prefix"""
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        with pytest.raises(ExpectedVersionError) as exc_info:
            with UnitOfWork() as uow:
                repo = test_domain.repository_for(Person)
                person = Person(first_name="Jane", last_name="Doe")
                repo.add(person)

                # Mock session.commit to raise ValueError with P0001 prefix
                for session in uow._sessions.values():
                    session.commit = Mock(
                        side_effect=ValueError(
                            "P0001-ERROR:  Expected version mismatch"
                        )
                    )

        assert str(exc_info.value) == "Expected version mismatch"

    def test_expected_version_error_handling_without_p0001_prefix(self, test_domain):
        """Test ExpectedVersionError handling when ValueError doesn't have P0001 prefix"""
        repo = test_domain.repository_for(Person)
        person = Person(first_name="John", last_name="Doe")
        repo.add(person)

        with pytest.raises(ExpectedVersionError) as exc_info:
            with UnitOfWork() as uow:
                repo = test_domain.repository_for(Person)
                person = Person(first_name="Jane", last_name="Doe")
                repo.add(person)

                # Mock session.commit to raise ValueError without P0001 prefix
                for session in uow._sessions.values():
                    session.commit = Mock(side_effect=ValueError("Version conflict"))

        assert str(exc_info.value) == "Version conflict"

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

            # Check that error was logged
            mock_logger.error.assert_called_once()
            assert "Error during Transaction rollback" in str(
                mock_logger.error.call_args
            )
            assert "Rollback failed" in str(mock_logger.error.call_args)

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
