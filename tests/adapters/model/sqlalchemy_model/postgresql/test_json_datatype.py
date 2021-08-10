from datetime import datetime

import pytest

from sqlalchemy import types as sa_types

from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import DateTime, Dict, String
from protean.globals import current_domain


class Event(BaseAggregate):
    name = String(max_length=255)
    created_at = DateTime(default=datetime.utcnow())
    payload = Dict()


@pytest.mark.postgresql
def test_json_data_type_association(test_domain):
    test_domain.register(Event)

    model_cls = test_domain.get_model(Event)
    type(model_cls.payload.property.columns[0].type) == sa_types.JSON


@pytest.mark.postgresql
def test_basic_dict_data_type_operations(test_domain):
    test_domain.register(Event)

    model_cls = test_domain.get_model(Event)

    event = Event(
        name="UserCreated", payload={"email": "john.doe@gmail.com", "password": "*****"}
    )
    event_model_obj = model_cls.from_entity(event)

    event_copy = model_cls.to_entity(event_model_obj)
    assert event_copy is not None
    assert event_copy.payload == {"email": "john.doe@gmail.com", "password": "*****"}


@pytest.mark.postgresql
def test_json_with_array_data(test_domain):
    test_domain.register(Event)

    model_cls = test_domain.get_model(Event)

    event = Event(
        name="UserCreated",
        payload=[
            {"email": "john.doe@gmail.com", "password": "*****"},
            {"email": "john.doe1234@gmail.com", "password": "*****"},
        ],
    )
    event_model_obj = model_cls.from_entity(event)

    event_copy = model_cls.to_entity(event_model_obj)
    assert event_copy is not None
    assert event_copy.payload == [
        {"email": "john.doe@gmail.com", "password": "*****"},
        {"email": "john.doe1234@gmail.com", "password": "*****"},
    ]


@pytest.mark.postgresql
def test_persistence_of_json_with_array_data(test_domain):
    test_domain.register(Event)

    event = Event(
        name="UserCreated",
        payload=[
            {"email": "john.doe@gmail.com", "password": "*****"},
            {"email": "john.doe1234@gmail.com", "password": "*****"},
        ],
    )
    current_domain.get_dao(Event).save(event)

    refreshed_event = current_domain.get_dao(Event).get(event.id)
    assert refreshed_event is not None
    assert refreshed_event.payload == [
        {"email": "john.doe@gmail.com", "password": "*****"},
        {"email": "john.doe1234@gmail.com", "password": "*****"},
    ]
