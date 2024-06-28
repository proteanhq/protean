import pytest

from protean import BaseAggregate, BaseEntity, BaseEvent, BaseValueObject
from protean.core.aggregate import element_to_fact_event
from protean.fields import HasMany, HasOne, Integer, List, String, ValueObject
from protean.reflection import declared_fields


class University(BaseAggregate):
    name = String(max_length=50)
    departments = HasMany("Department")


class Department(BaseEntity):
    name = String(max_length=50)
    dean = HasOne("Dean")


class Dean(BaseEntity):
    name = String(max_length=50)
    age = Integer(min_value=21)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(University)
    test_domain.register(Department, part_of=University)
    test_domain.register(Dean, part_of=Department)
    test_domain.init(traverse=False)


@pytest.fixture
def event_cls():
    return element_to_fact_event(University)


def test_fact_event_class_generation(event_cls):
    assert event_cls.__name__ == "UniversityFactEvent"
    assert issubclass(event_cls, BaseEvent)
    assert len(declared_fields(event_cls)) == 3

    assert all(
        field_name in declared_fields(event_cls)
        for field_name in ["name", "departments", "id"]
    )


def test_departments_is_a_list_of_value_objects(event_cls):
    departments_field = declared_fields(event_cls)["departments"]

    assert isinstance(departments_field, List)
    assert isinstance(departments_field.content_type, ValueObject)
    assert (
        departments_field.content_type._value_object_cls.__name__
        == "DepartmentValueObject"
    )


def test_dean_is_a_value_object(event_cls):
    departments_field = declared_fields(event_cls)["departments"]
    dean_field = declared_fields(departments_field.content_type._value_object_cls)[
        "dean"
    ]
    dean_vo_cls = dean_field._value_object_cls

    assert issubclass(dean_vo_cls, BaseValueObject)
    assert dean_vo_cls.__name__ == "DeanValueObject"


def test_department_value_object_fields(event_cls):
    departments_field = declared_fields(event_cls)["departments"]
    department_vo_cls = departments_field.content_type._value_object_cls

    assert len(declared_fields(department_vo_cls)) == 3
    assert all(
        field_name in declared_fields(department_vo_cls)
        for field_name in ["name", "dean", "id"]
    )


def test_dean_value_object_fields(event_cls):
    departments_field = declared_fields(event_cls)["departments"]
    dean_field = declared_fields(departments_field.content_type._value_object_cls)[
        "dean"
    ]
    dean_vo_cls = dean_field._value_object_cls

    assert len(declared_fields(dean_vo_cls)) == 3
    assert all(
        field_name in declared_fields(dean_vo_cls)
        for field_name in ["name", "age", "id"]
    )
