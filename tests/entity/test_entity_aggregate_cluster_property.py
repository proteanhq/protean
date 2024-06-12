import pytest

from protean import BaseAggregate, BaseEntity
from protean.fields import HasMany, HasOne, Integer, String


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


def test_aggregate_aggregate_cluster():
    assert University.meta_.aggregate_cluster == University


def test_entity_aggregate_cluster():
    assert Department.meta_.part_of == University
    assert Department.meta_.aggregate_cluster == University


def test_2nd_level_entity_aggregate_cluster():
    assert Dean.meta_.part_of == Department
    assert Dean.meta_.aggregate_cluster == University
