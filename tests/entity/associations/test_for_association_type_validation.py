import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import ValidationError
from protean.fields import HasMany, HasOne


class University(BaseAggregate):
    name: str | None = None
    departments = HasMany("Department")


class Department(BaseEntity):
    name: str | None = None
    dean = HasOne("Dean")


class Dean(BaseEntity):
    name: str | None = None
    age: int | None = None


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(University)
    test_domain.register(Department, part_of=University)
    test_domain.register(Dean, part_of=Department)
    test_domain.init(traverse=False)


def test_assignment_of_wrong_association_type_to_has_many():
    with pytest.raises(ValidationError):
        University(name="MIT", departments=Dean(name="John Doe", age=45))

    with pytest.raises(ValidationError):
        university = University(name="MIT")
        university.add_departments(Dean(name="John Doe", age=45))

    with pytest.raises(ValidationError):
        university = University(name="MIT")
        university.departments = Dean(name="John Doe", age=45)

    with pytest.raises(ValidationError):
        university = University(name="MIT")
        university.departments = [Dean(name="John Doe", age=45)]

    with pytest.raises(ValidationError):
        university = University(name="MIT")
        university.departments = [
            Department(name="Computer Science"),
            Dean(name="John Doe", age=45),
        ]


def test_assignment_of_wrong_association_type_to_has_one():
    with pytest.raises(ValidationError):
        Department(name="Computer Science", dean=University(name="MIT"))

    with pytest.raises(ValidationError):
        department = Department(name="Computer Science")
        department.dean = University(name="MIT")
