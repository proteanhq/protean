"""Tests for Status field creation and value validation."""

from enum import Enum

import pytest

from protean.core.value_object import BaseValueObject
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import Status
from protean.fields.spec import FieldSpec
from protean.utils.reflection import declared_fields


class OrderStatus(Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TestStatusFieldCreation:
    def test_status_requires_enum_class(self):
        with pytest.raises(IncorrectUsageError, match="requires an Enum class"):
            Status("not an enum")

    def test_status_requires_enum_class_not_list(self):
        with pytest.raises(IncorrectUsageError, match="requires an Enum class"):
            Status(["DRAFT", "PLACED"])

    def test_status_creates_fieldspec_with_string_type(self):
        spec = Status(OrderStatus)
        assert isinstance(spec, FieldSpec)
        assert spec.python_type is str

    def test_status_field_kind_is_status(self):
        spec = Status(OrderStatus)
        assert spec.field_kind == "status"

    def test_status_choices_set_from_enum(self):
        spec = Status(OrderStatus)
        assert spec.choices is OrderStatus

    def test_status_without_transitions(self):
        spec = Status(OrderStatus)
        assert spec.transitions is None

    def test_status_with_transitions_stores_normalized(self):
        spec = Status(
            OrderStatus,
            transitions={
                OrderStatus.DRAFT: [OrderStatus.PLACED, OrderStatus.CANCELLED],
                OrderStatus.PLACED: [OrderStatus.CONFIRMED],
            },
        )
        assert spec.transitions == {
            "DRAFT": ["PLACED", "CANCELLED"],
            "PLACED": ["CONFIRMED"],
        }

    def test_status_transitions_with_string_keys(self):
        spec = Status(
            OrderStatus,
            transitions={
                "DRAFT": ["PLACED"],
            },
        )
        assert spec.transitions == {"DRAFT": ["PLACED"]}

    def test_status_default_as_enum_value(self):
        spec = Status(OrderStatus, default="DRAFT")
        assert spec.default == "DRAFT"

    def test_status_default_as_enum_member(self):
        spec = Status(OrderStatus, default=OrderStatus.DRAFT)
        assert spec.default == "DRAFT"

    def test_status_required(self):
        spec = Status(OrderStatus, required=True)
        assert spec.required is True

    def test_status_repr_without_transitions(self):
        spec = Status(OrderStatus)
        assert repr(spec) == "Status()"

    def test_status_repr_with_transitions(self):
        spec = Status(
            OrderStatus,
            transitions={
                OrderStatus.DRAFT: [OrderStatus.PLACED, OrderStatus.CANCELLED],
                OrderStatus.PLACED: [OrderStatus.CONFIRMED],
            },
        )
        assert "transitions=<3 rules>" in repr(spec)

    def test_status_repr_with_default(self):
        spec = Status(OrderStatus, default="DRAFT")
        assert "default='DRAFT'" in repr(spec)


class TestStatusOnAggregate:
    def test_status_valid_value_accepted(self, test_domain):
        @test_domain.aggregate
        class Order:
            status = Status(OrderStatus, default="DRAFT")

        test_domain.init(traverse=False)

        order = Order()
        assert order.status == "DRAFT"

    def test_status_invalid_value_rejected(self, test_domain):
        @test_domain.aggregate
        class Order:
            status = Status(OrderStatus, default="DRAFT")

        test_domain.init(traverse=False)

        with pytest.raises(ValidationError):
            Order(status="INVALID")

    def test_status_enum_member_accepted_on_init(self, test_domain):
        """Enum members are coerced to their value by Pydantic Literal."""

        @test_domain.aggregate
        class Order:
            status = Status(OrderStatus, default="DRAFT")

        test_domain.init(traverse=False)

        # The status stores the string value
        order = Order(status="PLACED")
        assert order.status == "PLACED"


class TestStatusResolvedField:
    def test_resolved_field_has_transitions(self, test_domain):
        @test_domain.aggregate
        class Order:
            status = Status(
                OrderStatus,
                default="DRAFT",
                transitions={
                    OrderStatus.DRAFT: [OrderStatus.PLACED],
                },
            )

        test_domain.init(traverse=False)

        fields = declared_fields(Order)
        assert fields["status"].transitions == {"DRAFT": ["PLACED"]}

    def test_resolved_field_no_transitions(self, test_domain):
        @test_domain.aggregate
        class Order:
            status = Status(OrderStatus, default="DRAFT")

        test_domain.init(traverse=False)

        fields = declared_fields(Order)
        assert fields["status"].transitions is None

    def test_resolved_field_field_kind(self, test_domain):
        @test_domain.aggregate
        class Order:
            status = Status(OrderStatus, default="DRAFT")

        test_domain.init(traverse=False)

        fields = declared_fields(Order)
        assert fields["status"].field_kind == "status"


class TestStatusOnValueObject:
    def test_status_without_transitions_on_vo(self):
        """Status without transitions is allowed on VOs (just choices)."""

        class StatusVO(BaseValueObject):
            status: Status(OrderStatus)

        vo = StatusVO(status="DRAFT")
        assert vo.status == "DRAFT"

    def test_status_with_transitions_on_vo_rejected(self):
        with pytest.raises(
            IncorrectUsageError,
            match="Value Objects are immutable.*transitions",
        ):

            class StatusVO(BaseValueObject):
                status: Status(
                    OrderStatus,
                    transitions={OrderStatus.DRAFT: [OrderStatus.PLACED]},
                )
