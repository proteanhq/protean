from datetime import datetime

import pytest

from sqlalchemy import types as sa_types

from protean import BaseAggregate
from protean.fields import DateTime, Dict, String


class Event(BaseAggregate):
    name = String(max_length=255)
    created_at = DateTime(default=datetime.utcnow())
    payload = Dict()


@pytest.mark.sqlite
def test_json_data_type_association(test_domain):
    test_domain.register(Event)

    model_cls = test_domain.repository_for(Event)._model
    type(model_cls.payload.property.columns[0].type) == sa_types.PickleType


@pytest.mark.sqlite
def test_basic_array_data_type_operations(test_domain):
    test_domain.register(Event)

    model_cls = test_domain.repository_for(Event)._model

    event = Event(
        name="UserCreated", payload={"email": "john.doe@gmail.com", "password": "*****"}
    )
    event_model_obj = model_cls.from_entity(event)

    event_copy = model_cls.to_entity(event_model_obj)
    assert event_copy is not None
    assert event_copy.payload == {"email": "john.doe@gmail.com", "password": "*****"}
