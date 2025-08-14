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


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestHasManyWithHasOne:
    @pytest.fixture
    def university(self, test_domain):
        dean = Dean(id="dean-1", name="John Doe", age=45)
        department1 = Department(id="dept-1", name="Computer Science", dean=dean)
        department2 = Department(id="dept-2", name="Electrical Engineering")
        university = University(
            id="uni-1", name="MIT", departments=[department1, department2]
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

    def test_university_basic_structure(self):
        dean = Dean(id="dean-1", name="John Doe", age=45)
        department = Department(id="dept-1", name="Computer Science", dean=dean)
        university = University(id="uni-1", name="MIT", departments=[department])

        assert university.departments[0] == department
        assert department.university_id == university.id
        assert university.departments[0].dean == dean
        assert university.departments[0].dean.department_id == department.id

    def test_add_department_to_university(self, test_domain, university):
        department = Department(id="dept-3", name="Mechanical Engineering")
        university.add_departments(department)

        test_domain.repository_for(University).add(university)

        refreshed_university = test_domain.repository_for(University).get(university.id)

        assert len(refreshed_university.departments) == 3
        new_department = next(
            dept for dept in refreshed_university.departments if dept.id == "dept-3"
        )
        assert new_department == department
        assert new_department.university_id == university.id
        assert new_department.dean is None
