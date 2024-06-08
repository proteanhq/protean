import pytest

from protean import BaseAggregate, BaseEntity
from protean.fields import Integer, String, HasOne, HasMany


class University(BaseAggregate):
    name = String(max_length=50)
    departments = HasMany("Department")


class Department(BaseEntity):
    name = String(max_length=50)
    dean = HasOne("Dean")


class Dean(BaseEntity):
    name = String(max_length=50)
    age = Integer(min_value=21)
    office = HasOne("Office")


class Office(BaseEntity):
    building = String(max_length=25)
    room = Integer(min_value=1)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(University)
    test_domain.register(Department, part_of=University)
    test_domain.register(Dean, part_of=Department)
    test_domain.register(Office, part_of=Dean)
    test_domain.init(traverse=False)


def test_owner_linkage():
    office = Office(building="Main", room=101)
    dean = Dean(name="John Doe", age=45, office=office)
    department = Department(name="Computer Science", dean=dean)
    university = University(name="MIT", departments=[department])

    assert university._owner == university
    assert department._owner == university
    assert dean._owner == department
    assert office._owner == dean


def test_root_linkage_when_entities_are_constructed_in_advance():
    office = Office(building="Main", room=101)
    dean = Dean(name="John Doe", age=45, office=office)
    department = Department(name="Computer Science", dean=dean)
    university = University(name="MIT", departments=[department])

    assert university._root == university
    assert department._root == university
    assert dean._root == university
    assert office._root == university


def test_root_linkage_when_aggregate_and_entities_are_constructed_together():
    university = University(
        name="MIT",
        departments=[
            Department(
                name="Computer Science",
                dean=Dean(
                    name="John Doe", age=45, office=Office(building="Main", room=101)
                ),
            )
        ],
    )

    # Test owner linkages
    assert university._owner == university
    assert university.departments[0]._owner == university
    assert university.departments[0].dean._owner == university.departments[0]
    assert (
        university.departments[0].dean.office._owner == university.departments[0].dean
    )

    # Test root linkages
    assert university._root == university
    assert university.departments[0]._root == university
    assert university.departments[0].dean._root == university
    assert university.departments[0].dean.office._root == university


def test_root_linkage_is_preserved_after_persistence_and_retrieval(test_domain):
    university = University(
        name="MIT",
        departments=[
            Department(
                name="Computer Science",
                dean=Dean(
                    name="John Doe", age=45, office=Office(building="Main", room=101)
                ),
            )
        ],
    )

    test_domain.repository_for(University).add(university)

    refreshed_university = test_domain.repository_for(University).get(university.id)

    # Test owner linkages
    assert refreshed_university._owner == university
    assert refreshed_university.departments[0]._owner == refreshed_university
    assert (
        refreshed_university.departments[0].dean._owner
        == refreshed_university.departments[0]
    )
    assert (
        refreshed_university.departments[0].dean.office._owner
        == refreshed_university.departments[0].dean
    )

    # Test root linkages
    assert refreshed_university._root == refreshed_university
    assert refreshed_university.departments[0]._root == refreshed_university
    assert refreshed_university.departments[0].dean._root == refreshed_university
    assert refreshed_university.departments[0].dean.office._root == refreshed_university


def test_root_linkage_on_newly_added_entity(test_domain):
    university = University(
        name="MIT",
        departments=[
            Department(
                name="Computer Science",
                dean=Dean(
                    name="John Doe", age=45, office=Office(building="Main", room=101)
                ),
            )
        ],
    )

    new_department = Department(
        name="Electrical Engineering",
        dean=Dean(name="Jane Doe", age=42, office=Office(building="Main", room=102)),
    )

    assert new_department._root is None
    assert new_department.dean._root is None
    assert new_department.dean.office._root is None

    university.add_departments(new_department)

    # Test owner linkages
    assert new_department._owner == university
    assert new_department.dean._owner == new_department
    assert new_department.dean.office._owner == new_department.dean

    # Test root linkages
    assert new_department._root == university
    assert new_department.dean._root == university
    assert new_department.dean.office._root == university

    assert university.departments[1]._root == university
    assert university.departments[1].dean._root == university
    assert university.departments[1].dean.office._root == university

    test_domain.repository_for(University).add(university)

    refreshed_university = test_domain.repository_for(University).get(university.id)

    # Test owner linkages
    assert refreshed_university._owner == refreshed_university
    assert refreshed_university.departments[0]._owner == refreshed_university
    assert (
        refreshed_university.departments[0].dean._owner
        == refreshed_university.departments[0]
    )

    # Test root linkages
    assert refreshed_university.departments[1]._root == university
    assert refreshed_university.departments[1].dean._root == university
    assert refreshed_university.departments[1].dean.office._root == university
