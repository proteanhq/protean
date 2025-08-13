from datetime import UTC, datetime

import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, Dict, String


class Event(BaseAggregate):
    name = String(max_length=255)
    created_at = DateTime(default=datetime.now(UTC))
    payload = Dict()


@pytest.mark.postgresql
def test_persistence_and_retrieval(test_domain):
    test_domain.register(Event)
    test_domain.init(traverse=False)

    repo = test_domain.repository_for(Event)
    event = Event(
        name="UserCreated", payload={"email": "john.doe@gmail.com", "password": "*****"}
    )
    repo.add(event)

    event_dup = test_domain.repository_for(Event)._dao.find_by(name="UserCreated")
    assert event_dup is not None
    assert event_dup.payload is not None
    assert event_dup.payload == {"email": "john.doe@gmail.com", "password": "*****"}
