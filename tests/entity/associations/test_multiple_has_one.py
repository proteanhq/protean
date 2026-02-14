import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import HasOne, Integer, String
from protean.utils.reflection import declared_fields


class Department(BaseAggregate):
    name: String(max_length=50)
    dean = HasOne("Dean")
    location = HasOne("Location")


class Dean(BaseEntity):
    name: String(max_length=50)
    age: Integer(min_value=21)


class Location(BaseEntity):
    building: String(max_length=50)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Department)
    test_domain.register(Dean, part_of=Department)
    test_domain.register(Location, part_of=Department)
    test_domain.init(traverse=False)


def test_multiple_has_one_associations():
    assert declared_fields(Department)["dean"].__class__.__name__ == "HasOne"
    assert declared_fields(Department)["dean"].field_name == "dean"
    assert declared_fields(Department)["dean"].to_cls == Dean

    assert declared_fields(Department)["location"].__class__.__name__ == "HasOne"
    assert declared_fields(Department)["location"].field_name == "location"
    assert declared_fields(Department)["location"].to_cls == Location


def test_department_basic_structure():
    location = Location(building="Main Building")
    dean = Dean(name="John Doe", age=45)
    department = Department(name="Computer Science", dean=dean, location=location)

    assert department.dean == dean
    assert dean.department_id == department.id
    assert department.location == location
    assert location.department_id == department.id
    assert department.dean.department == department
    assert department.location.department == department


def test_basic_persistence(test_domain):
    location = Location(building="Main Building")
    dean = Dean(name="John Doe", age=45)
    department = Department(name="Computer Science", dean=dean, location=location)

    test_domain.repository_for(Department).add(department)

    persisted_department = test_domain.repository_for(Department).get(department.id)

    assert persisted_department.dean == dean
    assert persisted_department.location == location
    assert persisted_department.dean.department == persisted_department
    assert persisted_department.location.department == persisted_department
    assert persisted_department.dean.department_id == persisted_department.id
    assert persisted_department.location.department_id == persisted_department.id
