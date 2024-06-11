from protean import BaseEventSourcedAggregate
from protean.fields import Auto, DateTime, Identifier, Integer, String
from protean.reflection import fields, id_field, declared_fields
from protean.utils import utcnow_func


class User(BaseEventSourcedAggregate):
    name = String()
    age = Integer()


class Order(BaseEventSourcedAggregate):
    order_id = Identifier(identifier=True)
    placed_at = DateTime()


def test_auto_id_field_generation():
    assert "id" in fields(User)

    field_obj = fields(User)["id"]
    assert isinstance(field_obj, Auto)

    assert id_field(User) == field_obj


def test_no_auto_id_field_generation_when_an_identifier_is_provided():
    assert "id" not in fields(Order)

    field_obj = id_field(Order)
    assert field_obj.field_name == "order_id"


def test_that_an_aggregate_can_opt_to_have_no_id_field_by_default(test_domain):
    @test_domain.event_sourced_aggregate(auto_add_id_field=False)
    class TimeStamped:
        created_at = DateTime(default=utcnow_func)
        updated_at = DateTime(default=utcnow_func)

    assert "id" not in declared_fields(TimeStamped)
