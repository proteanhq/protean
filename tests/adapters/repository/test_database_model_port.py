"""What `DatabaseModelPort` requires of an adapter's database model class."""

import inspect
from abc import ABCMeta
from types import SimpleNamespace
from typing import Any, Protocol

import pytest

from protean.adapters.repository.elasticsearch import ElasticsearchModel
from protean.adapters.repository.memory import MemoryModel
from protean.adapters.repository.sqlalchemy import SqlalchemyModel
from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.fields import String
from protean.infra.dao import _stored_value
from protean.port.provider import DatabaseModelPort

PORT_SIGNATURES = {
    "from_entity": ["entity"],
    "to_entity": ["item"],
    "to_records": ["items", "fields"],
}


def test_the_port_declares_the_three_class_methods():
    assert DatabaseModelPort.__abstractmethods__ == frozenset(PORT_SIGNATURES)


@pytest.mark.parametrize("member", sorted(PORT_SIGNATURES))
def test_each_member_is_a_class_method_with_the_contract_parameters(member):
    assert isinstance(vars(DatabaseModelPort)[member], classmethod)

    parameters = list(inspect.signature(getattr(DatabaseModelPort, member)).parameters)
    assert parameters == PORT_SIGNATURES[member]


class TestMemoryModel:
    def test_subclasses_the_port_after_the_base_database_model(self):
        """`BaseDatabaseModel` comes first so its concrete `to_entity` and
        `to_records` win over the Port's abstract stubs, which return `None`."""
        assert MemoryModel.__bases__ == (BaseDatabaseModel, DatabaseModelPort)

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


def _register_person_model(domain: Any, model_cls: type) -> None:
    domain.register(Person)
    domain.register(model_cls, part_of=Person)
    domain.init(traverse=False)


class TestDecoratedMemoryModel:
    def test_round_trips_an_entity(self, test_domain):
        _register_person_model(test_domain, PersonModel)

        model_cls = test_domain.repository_for(Person)._database_model
        assert DatabaseModelPort in model_cls.__mro__

        person = Person(name="John")
        restored = model_cls.to_entity(model_cls.from_entity(person))

        assert restored.id == person.id
        assert restored.name == "John"

    def test_lives_in_the_memory_adapter_module(self, test_domain):
        _register_person_model(test_domain, PersonModel)

        model_cls = test_domain.repository_for(Person)._database_model
        assert model_cls.__module__ == "protean.adapters.repository.memory"

    def test_a_built_model_lives_in_the_memory_adapter_module(self, test_domain):
        test_domain.register(Person)
        test_domain.init(traverse=False)

        model_cls = test_domain.repository_for(Person)._database_model
        assert model_cls.__name__ == "PersonModel"
        assert model_cls.__module__ == "protean.adapters.repository.memory"

    def test_a_user_model_with_an_unrelated_metaclass_builds(self, test_domain):
        class CustomMeta(ABCMeta):
            pass

        class MetaPersonModel(BaseDatabaseModel, metaclass=CustomMeta):
            @classmethod
            def from_entity(cls, entity: Any) -> Any:
                return cls._entity_to_dict(entity)

        _register_person_model(test_domain, MetaPersonModel)

        model_cls = test_domain.repository_for(Person)._database_model
        assert issubclass(model_cls, MemoryModel)
        assert isinstance(model_cls, CustomMeta)
        assert isinstance(model_cls, type(Protocol))

        person = Person(name="John")
        restored = model_cls.to_entity(model_cls.from_entity(person))
        assert restored.name == "John"

    def test_a_user_model_with_a_protocol_derived_metaclass_builds(self, test_domain):
        class CustomMeta(type(Protocol)):
            pass

        class MetaPersonModel(BaseDatabaseModel, metaclass=CustomMeta):
            @classmethod
            def from_entity(cls, entity: Any) -> Any:
                return cls._entity_to_dict(entity)

        _register_person_model(test_domain, MetaPersonModel)

        model_cls = test_domain.repository_for(Person)._database_model
        assert issubclass(model_cls, MemoryModel)
        assert type(model_cls) is CustomMeta


class _AttributeModel:
    """A model class with no ``_get_value()``."""


class TestStoredValue:
    def test_the_default_reads_through_the_models_get_value(self):
        assert _stored_value(MemoryModel, {"name": "John"}, "name") == "John"

    def test_the_default_reads_an_attribute_without_get_value(self):
        record = SimpleNamespace(name="John")
        assert _stored_value(_AttributeModel, record, "name") == "John"

    def test_the_memory_dao_reads_a_dict_key(self, test_domain):
        test_domain.register(Person)
        test_domain.init(traverse=False)
        dao = test_domain.repository_for(Person)._dao

        assert _stored_value(dao.database_model_cls, {"name": "John"}, "name") == "John"
