import pytest

from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.core.entity import _LegacyBaseEntity as BaseEntity
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


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestHasManyWithHasOneWithHasOne:
    @pytest.fixture
    def university(self, test_domain):
        office = Office(id="1", building="Building 1", room=101)
        dean = Dean(id="2", name="John Doe", age=45, office=office)
        department1 = Department(id="31", name="Computer Science", dean=dean)
        department2 = Department(id="32", name="Electrical Engineering")
        university = University(
            id="4", name="MIT", departments=[department1, department2]
        )

        test_domain.repository_for(University).add(university)

        return test_domain.repository_for(University).get(university.id)

    def test_1st_level_associations(self):
        assert (
            declared_fields(University)["departments"].__class__.__name__ == "HasMany"
        )
        assert declared_fields(University)["departments"].field_name == "departments"
        assert declared_fields(University)["departments"].to_cls == Department

        assert declared_fields(Department)["dean"].__class__.__name__ == "HasOne"
        assert declared_fields(Department)["dean"].field_name == "dean"
        assert declared_fields(Department)["dean"].to_cls == Dean

        assert declared_fields(Dean)["office"].__class__.__name__ == "HasOne"
        assert declared_fields(Dean)["office"].field_name == "office"
        assert declared_fields(Dean)["office"].to_cls == Office

    def test_university_basic_structure(self):
        office = Office(building="Building 1", room=101)
        dean = Dean(name="John Doe", age=45, office=office)
        department = Department(name="Computer Science", dean=dean)
        university = University(name="MIT", departments=[department])

        assert university.departments[0] == department
        assert department.university_id == university.id
        assert university.departments[0].dean == dean
        assert university.departments[0].dean.department_id == department.id
        assert university.departments[0].dean.office == office
        assert university.departments[0].dean.office.dean_id == dean.id

    def test_switch_deans_office(self, test_domain, university):
        new_office = Office(building="Building 2", room=201)
        university.departments[0].dean.office = new_office

        test_domain.repository_for(University).add(university)

        university = test_domain.repository_for(University).get(university.id)
        assert university.departments[0].dean.office == new_office
        assert (
            university.departments[0].dean.office.dean_id
            == university.departments[0].dean.id
        )
