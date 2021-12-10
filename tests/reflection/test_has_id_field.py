from protean import BaseAggregate, BaseApplicationService, BaseCommand, BaseEntity
from protean.fields import String
from protean.fields.basic import Identifier
from protean.reflection import has_id_field


class Entity1(BaseEntity):
    foo = String()


class Aggregate1(BaseAggregate):
    foo = String()


class ApplicationService1(BaseApplicationService):
    pass


class CommandWithId(BaseCommand):
    foo_id = Identifier(identifier=True)


class CommandWithoutId(BaseCommand):
    foo_id = Identifier()


def test_elements_with_id_fields():
    assert has_id_field(Entity1) is True
    assert has_id_field(Aggregate1) is True


def test_elements_with_no_id_fields():
    assert has_id_field(ApplicationService1) is False


def test_elements_with_optional_id_field():
    assert has_id_field(CommandWithId) is True
    assert has_id_field(CommandWithoutId) is False
