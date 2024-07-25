import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import HasMany, HasOne, Integer, String
from protean.utils.reflection import declared_fields


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


def test_1st_level_associations():
    assert declared_fields(University)["departments"].__class__.__name__ == "HasMany"
    assert declared_fields(University)["departments"].field_name == "departments"
    assert declared_fields(University)["departments"].to_cls == Department

    assert declared_fields(Department)["dean"].__class__.__name__ == "HasOne"
    assert declared_fields(Department)["dean"].field_name == "dean"
    assert declared_fields(Department)["dean"].to_cls == Dean


def test_university_basic_structure():
    dean = Dean(name="John Doe", age=45)
    department = Department(name="Computer Science", dean=dean)
    university = University(name="MIT", departments=[department])

    assert university.departments[0] == department
    assert department.university_id == university.id
    assert university.departments[0].dean == dean
    assert university.departments[0].dean.department_id == department.id


@pytest.fixture
def university(test_domain):
    dean = Dean(name="John Doe", age=45)
    department1 = Department(name="Computer Science", dean=dean)
    department2 = Department(name="Electrical Engineering")
    university = University(name="MIT", departments=[department1, department2])

    test_domain.repository_for(University).add(university)

    return test_domain.repository_for(University).get(university.id)


def test_add_department_to_university(test_domain, university):
    department = Department(name="Mechanical Engineering")
    university.add_departments(department)

    test_domain.repository_for(University).add(university)

    refreshed_university = test_domain.repository_for(University).get(university.id)

    assert len(refreshed_university.departments) == 3
    assert refreshed_university.departments[2] == department
    assert refreshed_university.departments[2].university_id == university.id
    assert refreshed_university.departments[2].dean is None
