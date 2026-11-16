"""`Float` and `Integer` fields, and lists of them, reject `True` and `False`.

Pydantic's lax mode turns a bool into ``1``/``0`` or ``1.0``/``0.0``, which
let a wrongly typed flag pass validation and get stored as a number. Every
other value the fields accepted before is still accepted.
"""

from decimal import Decimal as PyDecimal

import pytest
from pydantic_core import PydanticCustomError

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import (
    Boolean,
    Decimal,
    Float,
    HasMany,
    Integer,
    List,
    String,
)
from protean.fields.spec import _reject_bool, _reject_bool_each


class Reading(BaseAggregate):
    temperature = Float()
    count = Integer()
    floats = List(content_type=Float)
    ints = List(content_type=Integer)
    plain_ints = List(int)
    nested_ints = List(content_type=List(content_type=Integer))
    names = List(content_type=String)
    level = Integer(choices=[1, 2])
    price = Decimal()
    active = Boolean()
    samples = HasMany("Sample")


class Sample(BaseEntity):
    temperature = Float()
    count = Integer()


class Measure(BaseValueObject):
    temperature = Float()
    count = Integer()


class RecordReading(BaseCommand):
    temperature = Float()
    count = Integer()


class ReadingRecorded(BaseEvent):
    temperature = Float()
    count = Integer()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Reading)
    test_domain.register(Sample, part_of=Reading)
    test_domain.register(Measure)
    test_domain.register(RecordReading, part_of=Reading)
    test_domain.register(ReadingRecorded, part_of=Reading)
    test_domain.init(traverse=False)


BOOLEANS = [True, False]
SCALAR_FIELDS = ["temperature", "count"]


def _assert_rejected(exc_info: pytest.ExceptionInfo[ValidationError], field: str):
    assert field in exc_info.value.messages
    assert exc_info.value.messages[field]
    assert "boolean" in exc_info.value.messages[field][0]


class TestScalarFieldsRejectBoolean:
    @pytest.mark.parametrize("flag", BOOLEANS)
    @pytest.mark.parametrize("field", SCALAR_FIELDS)
    def test_aggregate_construction(self, field, flag):
        with pytest.raises(ValidationError) as exc_info:
            Reading(**{field: flag})
        _assert_rejected(exc_info, field)

    @pytest.mark.parametrize("flag", BOOLEANS)
    @pytest.mark.parametrize("field", SCALAR_FIELDS)
    def test_aggregate_attribute_assignment(self, field, flag):
        reading = Reading(temperature=1.5, count=1)
        with pytest.raises(ValidationError) as exc_info:
            setattr(reading, field, flag)
        _assert_rejected(exc_info, field)
        assert reading.temperature == 1.5
        assert reading.count == 1

    @pytest.mark.parametrize("flag", BOOLEANS)
    @pytest.mark.parametrize("field", SCALAR_FIELDS)
    def test_entity(self, field, flag):
        with pytest.raises(ValidationError) as exc_info:
            Sample(**{field: flag})
        _assert_rejected(exc_info, field)

    @pytest.mark.parametrize("flag", BOOLEANS)
    @pytest.mark.parametrize("field", SCALAR_FIELDS)
    def test_value_object(self, field, flag):
        with pytest.raises(ValidationError) as exc_info:
            Measure(**{field: flag})
        _assert_rejected(exc_info, field)

    @pytest.mark.parametrize("flag", BOOLEANS)
    @pytest.mark.parametrize("field", SCALAR_FIELDS)
    def test_command(self, field, flag):
        with pytest.raises(ValidationError) as exc_info:
            RecordReading(**{field: flag})
        _assert_rejected(exc_info, field)

    @pytest.mark.parametrize("flag", BOOLEANS)
    @pytest.mark.parametrize("field", SCALAR_FIELDS)
    def test_event(self, field, flag):
        with pytest.raises(ValidationError) as exc_info:
            ReadingRecorded(**{field: flag})
        _assert_rejected(exc_info, field)

    def test_integer_with_choices(self):
        with pytest.raises(ValidationError) as exc_info:
            Reading(level=True)
        _assert_rejected(exc_info, "level")


class TestListFieldsRejectBoolean:
    @pytest.mark.parametrize("value", [[True], [1, True], [False, 2]])
    @pytest.mark.parametrize("field", ["floats", "ints", "plain_ints"])
    def test_list_with_a_boolean_element(self, field, value):
        with pytest.raises(ValidationError) as exc_info:
            Reading(**{field: value})
        _assert_rejected(exc_info, field)

    def test_nested_list_with_a_boolean_element(self):
        with pytest.raises(ValidationError) as exc_info:
            Reading(nested_ints=[[1, 2], [3, True]])
        _assert_rejected(exc_info, "nested_ints")

    def test_list_assignment_with_a_boolean_element(self):
        reading = Reading(ints=[1])
        with pytest.raises(ValidationError) as exc_info:
            reading.ints = [2, True]
        _assert_rejected(exc_info, "ints")
        assert reading.ints == [1]

    def test_non_list_value_is_reported_as_not_a_list(self):
        with pytest.raises(ValidationError) as exc_info:
            Reading(ints=True)
        assert exc_info.value.messages["ints"] == ["Input should be a valid list"]

    def test_string_list_is_unchanged(self):
        with pytest.raises(ValidationError) as exc_info:
            Reading(names=[True])
        assert exc_info.value.messages["names"] == ["Input should be a valid string"]


class TestAcceptedValuesAreUnchanged:
    def test_float_accepts_int_float_and_numeric_string(self):
        assert Reading(temperature=10).temperature == 10.0
        assert Reading(temperature=12.5).temperature == 12.5
        assert Reading(temperature="12.5").temperature == 12.5

    def test_integer_accepts_int_and_numeric_string(self):
        assert Reading(count=10).count == 10
        assert Reading(count="10").count == 10

    def test_numeric_lists_accept_numbers(self):
        reading = Reading(
            ints=[1, 2], floats=[1, 2.5], plain_ints=[0, 1], nested_ints=[[0], [1]]
        )
        assert reading.ints == [1, 2]
        assert reading.floats == [1.0, 2.5]
        assert reading.plain_ints == [0, 1]
        assert reading.nested_ints == [[0], [1]]

    def test_optional_fields_accept_none(self):
        reading = Reading(temperature=None, count=None)
        assert reading.temperature is None
        assert reading.count is None

    def test_integer_with_choices_accepts_a_choice(self):
        assert Reading(level=2).level == 2

    def test_boolean_still_accepts_a_boolean(self):
        assert Reading(active=True).active is True
        assert Reading(active=False).active is False

    def test_decimal_is_unchanged(self):
        assert Reading(price="1.5").price == PyDecimal("1.5")
        with pytest.raises(ValidationError) as exc_info:
            Reading(price=True)
        assert exc_info.value.messages["price"] == [
            "Decimal input should be an integer, float, string or Decimal object"
        ]


class TestValidatorHelpers:
    @pytest.mark.parametrize("value", [0, 1, 1.5, "1", None])
    def test_reject_bool_returns_non_boolean_unchanged(self, value):
        assert _reject_bool(value) == value

    @pytest.mark.parametrize("value", [None, "abc", 5, {"a": True}])
    def test_reject_bool_each_leaves_non_list_input_alone(self, value):
        assert _reject_bool_each(value) == value

    def test_reject_bool_each_checks_tuples(self):
        with pytest.raises(PydanticCustomError, match="boolean"):
            _reject_bool_each((1, (2, True)))
