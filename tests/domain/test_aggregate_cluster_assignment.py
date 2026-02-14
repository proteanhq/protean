import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.fields import HasMany, HasOne


class University(BaseAggregate):
    name: str | None = None
    departments = HasMany("Department")


class CloseDepartment(BaseCommand):
    department_id: int | None = None


class DepartmentClosed(BaseEvent):
    department_id: int | None = None


class Department(BaseEntity):
    name: str | None = None
    dean = HasOne("Dean")


class Dean(BaseEntity):
    name: str | None = None
    age: int | None = None


class TestAggregateClusterAssignment:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(University)
        test_domain.register(CloseDepartment, part_of=University)
        test_domain.register(DepartmentClosed, part_of=University)
        test_domain.register(Department, part_of=University)
        test_domain.register(Dean, part_of=Department)
        test_domain.init(traverse=False)

    def test_aggregate_cluster_assignment(self):
        assert University.meta_.aggregate_cluster == University
        assert Department.meta_.part_of == University
        assert Department.meta_.aggregate_cluster == University
        assert Dean.meta_.part_of == Department
        assert Dean.meta_.aggregate_cluster == University
        assert CloseDepartment.meta_.part_of == University
        assert CloseDepartment.meta_.aggregate_cluster == University
        assert DepartmentClosed.meta_.part_of == University
        assert DepartmentClosed.meta_.aggregate_cluster == University


class User(BaseAggregate):
    email: str | None = None
    name: str | None = None


class Register(BaseCommand):
    user_id: str | None = None
    email: str | None = None
    name: str | None = None


class Registered(BaseEvent):
    id: str | None = None
    email: str | None = None
    name: str | None = None
    password_hash: str | None = None


class TestEventSourcedAggregateClusterAssignment:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(User, is_event_sourced=True)
        test_domain.register(Register, part_of=User)
        test_domain.register(Registered, part_of=User)
        test_domain.init(traverse=False)

    def test_aggregate_cluster_assignment(self):
        assert User.meta_.aggregate_cluster == User
        assert Register.meta_.part_of == User
        assert Register.meta_.aggregate_cluster == User
        assert Registered.meta_.part_of == User
        assert Registered.meta_.aggregate_cluster == User
