import pytest
from unittest.mock import Mock, patch

from protean import UnitOfWork
from protean.exceptions import TransactionError, InvalidOperationError
from protean.utils import Processing

from .elements import Person, PersonRepository


class TestUnitOfWorkInitialization:
    def test_uow_can_be_initiated_with_context_manager(self, test_domain):
        with UnitOfWork() as uow:
            assert uow is not None
            assert uow.in_progress is True

    def test_uow_can_be_initiated_explicitly(self, test_domain):
        uow = UnitOfWork()
        assert uow is not None
        assert uow.in_progress is False

        uow.start()
        assert uow.in_progress is True

    def test_that_uow_throws_exception_on_commit_or_rollback_without_being_started(
        self, test_domain
    ):
        uow = UnitOfWork()

        with pytest.raises(InvalidOperationError):
            uow.commit()

        with pytest.raises(InvalidOperationError):
            uow.rollback()

    def test_that_uow_can_be_started_manually(self, test_domain):
        uow = UnitOfWork()

        uow.start()
        uow.commit()  # `commit` should not raise exception

        uow.start()
        uow.rollback()  # `rollback` should not raise exception


class TestUnitOfWorkAdditionalCoverage:
    """Additional tests to improve code coverage"""

    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonRepository, part_of=Person)
        test_domain.init(traverse=False)

    def test_context_manager_with_exception_triggers_rollback(self, test_domain):
        """Test that context manager properly handles exceptions by calling rollback"""
        repo = test_domain.repository_for(Person)

        with patch.object(UnitOfWork, "rollback") as mock_rollback:
            try:
                with UnitOfWork():
                    person = Person(first_name="Jane", last_name="Doe")
                    repo.add(person)
                    # Force an exception to trigger the rollback path
                    raise RuntimeError("Test exception")
            except RuntimeError:
                pass  # Expected exception

            # Verify rollback was called due to the exception
            mock_rollback.assert_called_once()

    @pytest.mark.skip(
        "This test unexpectedly fails unrelated tests in tests/unit_of_work/test_child_object_persistence.py"
    )
    def test_context_manager_commit_failure_triggers_rollback(self, test_domain):
        """Test that when commit fails in context manager, rollback is called"""
        repo = test_domain.repository_for(Person)

        with patch.object(UnitOfWork, "rollback") as mock_rollback:
            with patch.object(
                UnitOfWork, "commit", side_effect=TransactionError("Commit failed")
            ):
                with pytest.raises(TransactionError):
                    with UnitOfWork():
                        person = Person(first_name="Jane", last_name="Doe")
                        repo.add(person)

            # Verify rollback was called when commit failed
            mock_rollback.assert_called_once()

    def test_register_message_functionality(self, test_domain):
        """Test message registration functionality"""
        uow = UnitOfWork()

        # Initially no messages
        assert len(uow._messages_to_dispatch) == 0

        # Register a message
        uow.register_message("test_stream", {"data": "test"})

        # Check message was registered
        assert len(uow._messages_to_dispatch) == 1
        assert uow._messages_to_dispatch[0] == ("test_stream", {"data": "test"})

        # Register another message
        uow.register_message("another_stream", {"other": "data"})

        # Check both messages are registered
        assert len(uow._messages_to_dispatch) == 2
        assert uow._messages_to_dispatch[1] == ("another_stream", {"other": "data"})

    def test_message_dispatching_to_brokers(self, test_domain):
        """Test message dispatching to brokers"""
        uow = UnitOfWork()
        uow.start()

        # Register a message
        uow.register_message("test_stream", {"data": "test"})

        # Mock brokers
        mock_broker1 = Mock()
        mock_broker2 = Mock()
        test_domain.brokers = {"default": mock_broker1, "redis": mock_broker2}

        # Commit should dispatch messages to all brokers
        uow.commit()

        # Verify both brokers received the message
        mock_broker1.publish.assert_called_once_with("test_stream", {"data": "test"})
        mock_broker2.publish.assert_called_once_with("test_stream", {"data": "test"})

    def test_sync_event_processing(self, test_domain):
        """Test synchronous event processing"""
        # Enable sync event processing
        test_domain.config["event_processing"] = Processing.SYNC.value

        # Mock event handlers
        mock_handler1 = Mock()
        mock_handler2 = Mock()
        mock_handler1._handle = Mock()
        mock_handler2._handle = Mock()

        # Create a proper mock event with required attributes
        mock_event = Mock()
        mock_event.__class__ = Mock()
        mock_event.__class__.__type__ = "TestEvent.v1"
        mock_event._metadata = Mock()
        mock_event._metadata.id = "test-event-1"
        mock_event.to_dict = Mock(return_value={"test": "data"})

        with patch.object(
            test_domain, "handlers_for", return_value=[mock_handler1, mock_handler2]
        ):
            # Mock the event store to avoid issues with event serialization
            with patch.object(test_domain.event_store.store, "append"):
                uow = UnitOfWork()
                uow.start()

                # Simulate events in identity map
                mock_item = Mock()
                mock_item._events = [mock_event]
                uow._identity_map["default"]["test-id"] = mock_item

                uow.commit()

                # Verify handlers were called
                mock_handler1._handle.assert_called_once_with(mock_event)
                mock_handler2._handle.assert_called_once_with(mock_event)
