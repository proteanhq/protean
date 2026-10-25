"""A database model can name its target by string.

The string resolves at ``domain.init()``. The field check and the
duplicate check then run against the resolved target, with the same errors
a class target raises at registration.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.core.entity import BaseEntity
from protean.core.projection import BaseProjection
from protean.exceptions import ConfigurationError, IncorrectUsageError
from protean.fields import HasMany, Identifier, String, Text
from protean.ir.diagnostics import DiagnosticCode
from protean.utils import fqn


class Order(BaseAggregate):
    name = String()
    items = HasMany("LineItem")


class LineItem(BaseEntity):
    sku = String()


class OrderSummary(BaseProjection):
    order_id = Identifier(identifier=True)
    name = String()


class OrderModel(BaseDatabaseModel):
    name = Text()


class OtherOrderModel(BaseDatabaseModel):
    name = Text()


class BogusOrderModel(BaseDatabaseModel):
    name = Text()
    bogus = Text()


class TestStringTargetResolves:
    def test_model_registered_before_its_aggregate_resolves_at_init(self, test_domain):
        test_domain.register(OrderModel, part_of="Order")
        test_domain.register(Order)
        test_domain.register(LineItem, part_of=Order)
        test_domain.init(traverse=False)

        assert OrderModel.meta_.part_of is Order
        assert test_domain._database_models[fqn(Order)][None] is OrderModel

    def test_string_naming_a_projection_files_the_model_under_it(self, test_domain):
        test_domain.register(OrderSummary)
        test_domain.register(OrderModel, part_of="OrderSummary")
        test_domain.init(traverse=False)

        assert OrderModel.meta_.part_of is OrderSummary
        assert test_domain._database_models[fqn(OrderSummary)][None] is OrderModel

    def test_string_naming_an_entity_with_a_string_part_of(self, test_domain):
        class ItemModel(BaseDatabaseModel):
            sku = Text()

        test_domain.register(ItemModel, part_of="LineItem")
        test_domain.register(LineItem, part_of="Order")
        test_domain.register(Order)
        test_domain.init(traverse=False)

        assert ItemModel.meta_.part_of is LineItem
        assert test_domain._database_models[fqn(LineItem)][None] is ItemModel

    def test_a_string_model_is_not_filed_before_init(self, test_domain):
        test_domain.register(Order)
        test_domain.register(LineItem, part_of=Order)
        test_domain.register(OrderModel, part_of="Order")

        assert None not in test_domain._database_models[fqn(Order)]

    def test_a_second_init_does_not_file_the_model_again(self, test_domain):
        test_domain.register(Order)
        test_domain.register(LineItem, part_of=Order)
        test_domain.register(OrderModel, part_of="Order")
        test_domain.init(traverse=False)
        test_domain.init(traverse=False)

        assert test_domain._database_models[fqn(Order)] == {None: OrderModel}


class TestStringTargetErrors:
    def test_an_unknown_name_fails_init_naming_model_and_target(self, test_domain):
        test_domain.register(Order)
        test_domain.register(LineItem, part_of=Order)
        test_domain.register(OrderModel, part_of="Ordr")

        with pytest.raises(ConfigurationError) as exc:
            test_domain.init(traverse=False)

        assert "`OrderModel` references `Ordr` via part_of" in str(exc.value)
        assert "Ordr" not in test_domain._database_models

    def test_an_extra_field_fails_at_init_with_the_class_form_message(
        self, test_domain
    ):
        # Registration succeeds: the target is not known yet.
        test_domain.register(BogusOrderModel, part_of="Order")
        test_domain.register(Order)
        test_domain.register(LineItem, part_of=Order)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert str(exc.value) == (
            "Database Model `BogusOrderModel` has field(s) {'bogus'} "
            "not declared in `Order`"
        )

    def test_two_string_models_for_one_target_and_database_fail_init(self, test_domain):
        test_domain.register(Order)
        test_domain.register(LineItem, part_of=Order)
        test_domain.register(OrderModel, part_of="Order")
        test_domain.register(OtherOrderModel, part_of="Order")

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.code == DiagnosticCode.USAGE_DUPLICATE_DATABASE_MODEL
        assert str(exc.value) == (
            "A database model for `Order` targeting database `None` "
            "is already registered"
        )

    def test_a_class_model_and_a_string_model_for_one_target_fail_init(
        self, test_domain
    ):
        test_domain.register(Order)
        test_domain.register(LineItem, part_of=Order)
        test_domain.register(OrderModel, part_of=Order, database="sqlite")
        test_domain.register(OtherOrderModel, part_of="Order", database="sqlite")

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.code == DiagnosticCode.USAGE_DUPLICATE_DATABASE_MODEL

    def test_string_models_for_different_databases_both_file(self, test_domain):
        test_domain.register(Order)
        test_domain.register(LineItem, part_of=Order)
        test_domain.register(OrderModel, part_of="Order", database="sqlite")
        test_domain.register(OtherOrderModel, part_of="Order", database="postgresql")
        test_domain.init(traverse=False)

        assert test_domain._database_models[fqn(Order)] == {
            "sqlite": OrderModel,
            "postgresql": OtherOrderModel,
        }


class TestClassTargetIsUnchanged:
    def test_an_extra_field_still_fails_at_registration(self, test_domain):
        test_domain.register(Order)

        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.register(BogusOrderModel, part_of=Order)

        assert "bogus" in str(exc.value)

    def test_a_class_model_is_filed_at_registration(self, test_domain):
        test_domain.register(Order)
        test_domain.register(OrderModel, part_of=Order)

        assert test_domain._database_models[fqn(Order)][None] is OrderModel
