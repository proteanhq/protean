from datetime import datetime

from pydantic import Field as PydanticField

from protean.core.aggregate import BaseAggregate
from protean.utils import utcnow_func
from protean.utils.reflection import declared_fields, fields, id_field


class User(BaseAggregate):
    name: str | None = None
    age: int | None = None


class Order(BaseAggregate):
    order_id: str = PydanticField(json_schema_extra={"identifier": True})
    placed_at: datetime | None = None


def test_auto_id_field_generation():
    assert "id" in fields(User)

    field_obj = fields(User)["id"]
    assert field_obj.identifier is True

    assert id_field(User) == field_obj


def test_no_auto_id_field_generation_when_an_identifier_is_provided():
    assert "id" not in fields(Order)

    field_obj = id_field(Order)
    assert field_obj.field_name == "order_id"


def test_that_an_aggregate_can_opt_to_have_no_id_field_by_default(test_domain):
    @test_domain.aggregate(is_event_sourced=True, auto_add_id_field=False)
    class TimeStamped:
        created_at: datetime = PydanticField(default_factory=utcnow_func)
        updated_at: datetime = PydanticField(default_factory=utcnow_func)

    assert "id" not in declared_fields(TimeStamped)
