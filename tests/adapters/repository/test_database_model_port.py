"""What `DatabaseModelPort` requires of an adapter's database model class."""

from typing import Any

import pytest

from protean.adapters.repository.elasticsearch import ElasticsearchModel
from protean.adapters.repository.memory import MemoryModel
from protean.adapters.repository.sqlalchemy import SqlalchemyModel
from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.fields import String
from protean.port.provider import DatabaseModelPort

MODEL_PORT_MEMBERS = sorted(DatabaseModelPort.__abstractmethods__)


def _stub_model(*, without: str | None = None) -> type:
    """A subclass of the Port that implements every member except `without`."""
    members: dict[str, Any] = {
        name: classmethod(lambda cls, *args: None)
        for name in DatabaseModelPort.__abstractmethods__
        if name != without
    }
    return type("StubModel", (DatabaseModelPort,), members)


def test_the_port_declares_the_three_class_methods():
    assert MODEL_PORT_MEMBERS == ["from_entity", "to_entity", "to_records"]


@pytest.mark.parametrize("member", MODEL_PORT_MEMBERS)
def test_a_model_missing_a_member_cannot_be_built(member):
    with pytest.raises(TypeError, match=member):
        _stub_model(without=member)()


def test_a_model_with_every_member_can_be_built():
    model_cls = _stub_model()

    assert model_cls.__abstractmethods__ == frozenset()
    assert type(model_cls()) is model_cls


class TestMemoryModel:
    def test_subclasses_the_port_after_the_base_database_model(self):
        bases = MemoryModel.__bases__
        assert bases == (BaseDatabaseModel, DatabaseModelPort)

    def test_implements_every_port_member(self):
        assert MemoryModel.__abstractmethods__ == frozenset()


@pytest.mark.parametrize("model_cls", [SqlalchemyModel, ElasticsearchModel])
def test_a_model_with_a_library_metaclass_cannot_subclass_the_port(model_cls):
    with pytest.raises(TypeError, match="metaclass conflict"):
        type("ConflictingModel", (model_cls, DatabaseModelPort), {})


class Person(BaseAggregate):
    name: String(max_length=50)


class PersonModel(BaseDatabaseModel):
    @classmethod
    def from_entity(cls, entity: Any) -> Any:
        return cls._entity_to_dict(entity)


def test_a_memory_model_decorated_from_a_user_model_round_trips(test_domain):
    test_domain.register(Person)
    test_domain.register(PersonModel, part_of=Person)
    test_domain.init(traverse=False)

    model_cls = test_domain.repository_for(Person)._database_model
    assert DatabaseModelPort in model_cls.__mro__

    person = Person(name="John")
    restored = model_cls.to_entity(model_cls.from_entity(person))

    assert restored.id == person.id
    assert restored.name == "John"
