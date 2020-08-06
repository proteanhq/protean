# Standard Library Imports
from datetime import datetime

# Protean
import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import JSON, DateTime, String


class Event(BaseAggregate):
    name = String(max_length=255)
    created_at = DateTime(default=datetime.utcnow())
    payload = JSON()


@pytest.mark.postgresql
def test_basic_array_data_type_support(test_domain):
    test_domain.register(Event)

    model_cls = test_domain.get_model(Event)
    event = Event(
        name="UserCreated", payload={"email": "john.doe@gmail.com", "password": "*****"}
    )
    event_model_obj = model_cls.from_entity(event)

    event_copy = model_cls.to_entity(event_model_obj)
    assert event_copy is not None
    assert event_copy.payload == {"email": "john.doe@gmail.com", "password": "*****"}
