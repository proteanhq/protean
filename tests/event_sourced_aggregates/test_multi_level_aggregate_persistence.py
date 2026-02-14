import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.entity import BaseEntity
from protean.core.event import _LegacyBaseEvent as LegacyBaseEvent
from protean.core.event import BaseEvent
from protean.core.value_object import (
    _LegacyBaseValueObject as LegacyBaseValueObject,
)
from protean.fields import (
    HasMany,
    HasOne,
    Identifier,
    Integer,
    List,
    String,
    ValueObject,
)


class Department(BaseEntity):
    name: str | None = None
    dean = HasOne("Dean")


class Dean(BaseEntity):
    name: str | None = None
    age: int | None = None
    office = HasOne("Office")


class Office(BaseEntity):
    building: str | None = None
    room: int | None = None


# These VOs use ValueObject() descriptors, so they must stay on legacy base.
class OfficeVO(LegacyBaseValueObject):
    id = Identifier()
    building = String(max_length=25)
    room = Integer(min_value=1)


class DeanVO(LegacyBaseValueObject):
    id = Identifier()
    name = String(max_length=50)
    age = Integer(min_value=21)
    office = ValueObject(OfficeVO)


class DepartmentVO(LegacyBaseValueObject):
    id = Identifier()
    name = String(max_length=50)
    dean = ValueObject(DeanVO)


# This event uses ValueObject() and List(content_type=ValueObject(...)) descriptors,
# so it must stay on the legacy base.
class UniversityCreated(LegacyBaseEvent):
    id = Identifier(identifier=True)
    name = String(max_length=50)
    departments = List(content_type=ValueObject(DepartmentVO))


class NameChanged(BaseEvent):
    id: str | None = None
    name: str | None = None


class University(BaseAggregate):
    name: str | None = None
    departments = HasMany(Department)

    def raise_event(self):
        self.raise_(UniversityCreated(**self.to_dict()))

    def change_name(self, name):
        self.name = name
        self.raise_(NameChanged(id=self.id, name=name))

    @apply
    def on_university_created(self, event: UniversityCreated):
        # We are not doing anything here, because Protean applies
        #   the first event automatically, with from_events
        pass

    @apply
    def on_name_changed(self, event: NameChanged):
        self.name = event.name


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(University, is_event_sourced=True)
    test_domain.register(Department, part_of=University)
    test_domain.register(Dean, part_of=Department)
    test_domain.register(Office, part_of=Dean)
    test_domain.register(UniversityCreated, part_of=University)
    test_domain.register(NameChanged, part_of=University)
    test_domain.init(traverse=False)


@pytest.fixture
def university(test_domain):
    university = University(
        name="MIT",
        departments=[
            Department(
                name="Computer Science",
                dean=Dean(
                    name="John Doe", age=45, office=Office(building="NE43", room=123)
                ),
            ),
            Department(
                name="Electrical Engineering",
                dean=Dean(
                    name="Jane Smith", age=50, office=Office(building="NE43", room=124)
                ),
            ),
        ],
    )
    university.raise_event()
    test_domain.repository_for(University).add(university)

    return university


def test_aggregate_persistence(test_domain, university):
    refreshed_university = test_domain.repository_for(University).get(university.id)

    assert refreshed_university.id == university.id
    assert refreshed_university.name == university.name
    assert len(refreshed_university.departments) == 2
    assert refreshed_university.departments[0].name == university.departments[0].name
    assert refreshed_university.departments[1].name == university.departments[1].name
    assert (
        refreshed_university.departments[0].dean.name
        == university.departments[0].dean.name
    )
    assert (
        refreshed_university.departments[1].dean.name
        == university.departments[1].dean.name
    )
    assert (
        refreshed_university.departments[0].dean.office.building
        == university.departments[0].dean.office.building
    )
    assert (
        refreshed_university.departments[1].dean.office.building
        == university.departments[1].dean.office.building
    )
    assert (
        refreshed_university.departments[0].dean.office.room
        == university.departments[0].dean.office.room
    )
    assert (
        refreshed_university.departments[1].dean.office.room
        == university.departments[1].dean.office.room
    )


def test_aggregate_persistence_after_update(test_domain, university):
    refreshed_university = test_domain.repository_for(University).get(university.id)

    refreshed_university.change_name("Harvard")
    test_domain.repository_for(University).add(refreshed_university)

    refreshed_university = test_domain.repository_for(University).get(
        refreshed_university.id
    )

    assert refreshed_university.name == "Harvard"
