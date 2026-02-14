import pytest
from sqlalchemy import types as sa_types

from protean.core.aggregate import BaseAggregate
from protean.fields import DateTime, Dict, String
from protean.utils import utcnow_func
from protean.utils.globals import current_domain


class Event(BaseAggregate):
    name: String(max_length=255)
    created_at: DateTime(default=utcnow_func)
    payload: Dict()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Event)
    test_domain.init(traverse=False)


@pytest.mark.postgresql
def test_json_data_type_association(test_domain):
    database_model_cls = test_domain.repository_for(Event)._database_model
    type(database_model_cls.payload.property.columns[0].type) is sa_types.JSON


@pytest.mark.postgresql
def test_basic_dict_data_type_operations(test_domain):
    database_model_cls = test_domain.repository_for(Event)._database_model

    event = Event(
        name="UserCreated", payload={"email": "john.doe@gmail.com", "password": "*****"}
    )
    event_model_obj = database_model_cls.from_entity(event)

    event_copy = database_model_cls.to_entity(event_model_obj)
    assert event_copy is not None
    assert event_copy.payload == {"email": "john.doe@gmail.com", "password": "*****"}


@pytest.mark.postgresql
def test_json_with_array_data(test_domain):
    database_model_cls = test_domain.repository_for(Event)._database_model

    event = Event(
        name="UserCreated",
        payload=[
            {"email": "john.doe@gmail.com", "password": "*****"},
            {"email": "john.doe1234@gmail.com", "password": "*****"},
        ],
    )
    event_model_obj = database_model_cls.from_entity(event)

    event_copy = database_model_cls.to_entity(event_model_obj)
    assert event_copy is not None
    assert event_copy.payload == [
        {"email": "john.doe@gmail.com", "password": "*****"},
        {"email": "john.doe1234@gmail.com", "password": "*****"},
    ]


@pytest.mark.postgresql
def test_persistence_of_json_with_array_data(test_domain):
    event = Event(
        name="UserCreated",
        payload=[
            {"email": "john.doe@gmail.com", "password": "*****"},
            {"email": "john.doe1234@gmail.com", "password": "*****"},
        ],
    )
    current_domain.repository_for(Event).add(event)

    refreshed_event = current_domain.repository_for(Event).get(event.id)
    assert refreshed_event is not None
    assert refreshed_event.payload == [
        {"email": "john.doe@gmail.com", "password": "*****"},
        {"email": "john.doe1234@gmail.com", "password": "*****"},
    ]
