import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, Integer, String
from datetime import datetime


class Event(BaseAggregate):
    name = String(max_length=255, required=True)
    created_at = DateTime(default=datetime.now())
    sequence_id = Integer()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Event)
    test_domain.init(traverse=False)


@pytest.mark.database
class TestBasicPersistence:
    """Test basic persistence operations across SQLAlchemy databases"""

    def test_persist_and_retrieve_entity(self, test_domain):
        """Test basic entity persistence and retrieval"""
        event = Event(name="TestEvent", sequence_id=1)
        test_domain.repository_for(Event).add(event)

        retrieved_event = test_domain.repository_for(Event).get(event.id)

        assert retrieved_event.id == event.id
        assert retrieved_event.name == event.name
        assert retrieved_event.sequence_id == event.sequence_id

    def test_entity_update(self, test_domain):
        """Test entity update operations"""
        event = Event(name="TestEvent", sequence_id=1)
        test_domain.repository_for(Event).add(event)

        # Fetch the event again
        retrieved_event = test_domain.repository_for(Event).get(event.id)

        # Update the event
        retrieved_event.name = "UpdatedEvent"
        retrieved_event.sequence_id = 2
        test_domain.repository_for(Event).add(retrieved_event)

        # Retrieve and verify
        retrieved_event = test_domain.repository_for(Event).get(event.id)
        assert retrieved_event.name == "UpdatedEvent"
        assert retrieved_event.sequence_id == 2
