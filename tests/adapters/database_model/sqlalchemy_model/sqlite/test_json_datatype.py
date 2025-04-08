import pytest
from sqlalchemy import types as sa_types

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, Dict, String
from protean.utils import utcnow_func


class Event(BaseAggregate):
    name = String(max_length=255)
    created_at = DateTime(default=utcnow_func)
    payload = Dict()


@pytest.mark.sqlite
def test_json_data_type_association(test_domain):
    test_domain.register(Event)

    database_model_cls = test_domain.repository_for(Event)._database_model
    type(database_model_cls.payload.property.columns[0].type) is sa_types.PickleType


@pytest.mark.sqlite
def test_basic_array_data_type_operations(test_domain):
    test_domain.register(Event)

    database_model_cls = test_domain.repository_for(Event)._database_model

    event = Event(
        name="UserCreated", payload={"email": "john.doe@gmail.com", "password": "*****"}
    )
    event_model_obj = database_model_cls.from_entity(event)

    event_copy = database_model_cls.to_entity(event_model_obj)
    assert event_copy is not None
    assert event_copy.payload == {"email": "john.doe@gmail.com", "password": "*****"}
