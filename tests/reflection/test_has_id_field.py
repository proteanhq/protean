from pydantic import Field

from protean.core.aggregate import BaseAggregate
from protean.core.application_service import BaseApplicationService
from protean.core.command import BaseCommand
from protean.core.entity import BaseEntity
from protean.utils.reflection import has_id_field


class Aggregate1(BaseAggregate):
    foo: str | None = None


class Entity1(BaseEntity):
    foo: str | None = None


class ApplicationService1(BaseApplicationService):
    pass


class CommandWithId(BaseCommand):
    foo_id: str = Field(json_schema_extra={"identifier": True})


class CommandWithoutId(BaseCommand):
    foo_id: str | None = None


def test_elements_with_id_fields():
    assert has_id_field(Entity1) is True
    assert has_id_field(Aggregate1) is True


def test_elements_with_no_id_fields():
    assert has_id_field(ApplicationService1) is False


def test_elements_with_optional_id_field():
    assert has_id_field(CommandWithId) is True
    assert has_id_field(CommandWithoutId) is False
