import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import _LegacyBaseEvent as BaseEvent
from protean.fields import HasOne, Integer, String, ValueObject
from protean.utils.reflection import declared_fields


class Department(BaseAggregate):
    name = String(max_length=50)
    dean = HasOne("Dean")


class Dean(BaseEntity):
    name = String(max_length=50)
    age = Integer(min_value=21)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Department, fact_events=True)
    test_domain.register(Dean, part_of=Department)
    test_domain.init(traverse=False)


@pytest.fixture
def event_cls():
    return Department._fact_event_cls


def test_fact_event_class_generation(event_cls):
    assert event_cls.__name__ == "DepartmentFactEvent"
    assert issubclass(event_cls, BaseEvent)
    assert len(declared_fields(event_cls)) == 3

    assert all(
        field_name in declared_fields(event_cls)
        for field_name in ["name", "dean", "id"]
    )


def test_entity_is_a_value_object(event_cls):
    dean_field = declared_fields(event_cls)["dean"]

    assert isinstance(dean_field, ValueObject)
    assert dean_field.value_object_cls.__name__ == "DeanValueObject"


def test_dean_value_object_fields(event_cls):
    dean_field = declared_fields(event_cls)["dean"]
    dean_vo_cls = dean_field.value_object_cls

    assert len(declared_fields(dean_vo_cls)) == 3
    assert all(
        field_name in declared_fields(dean_vo_cls)
        for field_name in ["name", "age", "id"]
    )
