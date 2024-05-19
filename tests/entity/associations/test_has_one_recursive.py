import pytest

from protean import BaseAggregate, BaseEntity
from protean.fields import Integer, String, HasOne
from protean.reflection import declared_fields


class University(BaseAggregate):
    name = String(max_length=50)
    dean = HasOne("Dean")


class Dean(BaseEntity):
    name = String(max_length=50)
    age = Integer(min_value=21)
    office = HasOne("Office")

    class Meta:
        part_of = University


class Office(BaseEntity):
    building = String(max_length=25)
    room = Integer(min_value=1)

    class Meta:
        part_of = Dean


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(University)
    test_domain.register(Dean)
    test_domain.register(Office)
    test_domain.init(traverse=False)


def test_1st_level_associations():
    assert declared_fields(Dean)["office"].__class__.__name__ == "HasOne"
    assert declared_fields(Dean)["office"].field_name == "office"
    assert declared_fields(Dean)["office"].to_cls == Office


def test_university_basic_structure():
    office = Office(building="Main Building", room=101)
    dean = Dean(name="John Doe", age=45, office=office)
    university = University(name="MIT", dean=dean)

    assert university.dean == dean
    assert dean.university_id == university.id
    assert university.dean.office == office
    assert university.dean.office.dean_id == dean.id


@pytest.fixture
def university(test_domain):
    office = Office(building="Main Building", room=101)
    dean = Dean(name="John Doe", age=45, office=office)
    university = University(name="MIT", dean=dean)

    test_domain.repository_for(University).add(university)

    # Reload the university from the repository
    return test_domain.repository_for(University).get(university.id)


def test_switch_1st_level_has_one_entity(test_domain, university):
    university.dean = Dean(
        name="Jane Doe", age=50, office=Office(building="Main Building", room=102)
    )

    test_domain.repository_for(University).add(university)

    # Reload the university from the repository
    reloaded_university = test_domain.repository_for(University).get(university.id)

    assert reloaded_university.dean.name == "Jane Doe"
    assert reloaded_university.dean.office.room == 102


def test_direct_update_1st_level_has_one_entity(test_domain, university):
    university.dean.age = 55

    test_domain.repository_for(University).add(university)

    # Reload the university from the repository
    reloaded_university = test_domain.repository_for(University).get(university.id)

    assert reloaded_university.dean.name == "John Doe"
    assert reloaded_university.dean.age == 55


def test_switch_2nd_level_has_one_entity(test_domain, university):
    university.dean.office = Office(building="Main Building", room=103)

    test_domain.repository_for(University).add(university)

    # Reload the university from the repository
    reloaded_university = test_domain.repository_for(University).get(university.id)

    assert reloaded_university.dean.office.room == 103
    assert reloaded_university.dean.office.building == "Main Building"
    assert reloaded_university.dean.name == "John Doe"
    assert reloaded_university.dean.age == 45


def test_direct_update_2nd_level_has_one_entity(test_domain, university):
    university.dean.office.room = 104

    test_domain.repository_for(University).add(university)

    # Reload the university from the repository
    reloaded_university = test_domain.repository_for(University).get(university.id)

    assert reloaded_university.dean.office.room == 104
    assert reloaded_university.dean.office.building == "Main Building"
    assert reloaded_university.dean.name == "John Doe"
    assert reloaded_university.dean.age == 45


def test_reset_1st_level_has_one_entity(test_domain, university):
    university.dean = None

    test_domain.repository_for(University).add(university)

    # Reload the university from the repository
    reloaded_university = test_domain.repository_for(University).get(university.id)

    assert reloaded_university.dean is None


def test_reset_2nd_level_has_one_entity(test_domain, university):
    university.dean.office = None

    test_domain.repository_for(University).add(university)

    # Reload the university from the repository
    reloaded_university = test_domain.repository_for(University).get(university.id)

    assert reloaded_university.dean.office is None
    assert reloaded_university.dean.name == "John Doe"
    assert reloaded_university.dean.age == 45
