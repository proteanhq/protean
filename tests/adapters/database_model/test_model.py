import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.exceptions import IncorrectUsageError
from protean.fields import Integer, String, Text
from protean.utils import fully_qualified_name

from tests.adapters.database_model.dict_model.elements import (
    Provider,
    ProviderCustomModel,
)


@pytest.mark.database
class TestSchemaNameDerivation:
    def test_that_explicit_schema_name_is_used_if_provided(self, test_domain):
        test_domain.register(Provider)
        test_domain.register(
            ProviderCustomModel, part_of=Provider, schema_name="adults"
        )

        assert ProviderCustomModel.derive_schema_name() == "adults"

    def test_that_schema_name_is_derived_from_entity_name_if_not_provided(
        self, test_domain
    ):
        test_domain.register(Provider)
        test_domain.register(ProviderCustomModel, part_of=Provider)

        assert ProviderCustomModel.derive_schema_name() == "provider"

    def test_that_overridden_schema_name_in_entity_is_used_if_provided(
        self, test_domain
    ):
        test_domain.register(Provider, schema_name="adults")
        test_domain.register(ProviderCustomModel, part_of=Provider)

        assert ProviderCustomModel.derive_schema_name() == "adults"

    def test_same_model_is_returned_once_generated(self, test_domain):
        test_domain.register(Provider)
        test_domain.register(ProviderCustomModel, part_of=Provider)

        model1 = test_domain.repository_for(Provider)._database_model
        model2 = test_domain.repository_for(Provider)._database_model
        assert model1 is model2


@pytest.mark.database
class TestModelCacheByFQN:
    """B3: Model cache uses fully qualified name, not schema_name.

    Two aggregates with the same class name (but different modules) should
    get distinct model classes, not collide in the provider's cache.
    """

    def test_same_class_name_different_modules_get_distinct_models(self, test_domain):
        """Two aggregates named 'Item' defined in different scopes should
        produce separate model classes in the provider cache."""

        # Define two aggregates with the same class name but different attributes
        # They will have different fully_qualified_names because they are defined
        # in different local scopes (different qualnames)
        class Item(BaseAggregate):
            name = String(max_length=50)

        class ItemNamespace:
            """Simulate a different module by nesting the class."""

            class Item(BaseAggregate):
                code = Integer()

        test_domain.register(Item)
        test_domain.register(ItemNamespace.Item)

        model1 = test_domain.repository_for(Item)._database_model
        model2 = test_domain.repository_for(ItemNamespace.Item)._database_model

        # The two model classes should be distinct
        assert model1 is not model2

        # Verify they map to their respective aggregates
        assert model1.meta_.part_of is Item
        assert model2.meta_.part_of is ItemNamespace.Item


@pytest.mark.database
class TestMultipleModelsPerAggregate:
    """Multiple custom database models can be registered for the same aggregate,
    each targeting a different database type."""

    def test_two_models_for_same_aggregate_different_databases(self, test_domain):
        """Registering models with different `database` values should not
        overwrite each other."""

        class Order(BaseAggregate):
            name = String(max_length=100)

        class OrderMemoryModel(BaseDatabaseModel):
            name = Text()

        class OrderOtherModel(BaseDatabaseModel):
            name = Text()

        test_domain.register(Order)
        test_domain.register(OrderMemoryModel, part_of=Order, database="memory")
        test_domain.register(OrderOtherModel, part_of=Order, database="postgresql")

        entity_key = fully_qualified_name(Order)
        assert "memory" in test_domain._database_models[entity_key]
        assert "postgresql" in test_domain._database_models[entity_key]
        assert test_domain._database_models[entity_key]["memory"] is OrderMemoryModel
        assert test_domain._database_models[entity_key]["postgresql"] is OrderOtherModel

    def test_type_specific_model_is_resolved_over_generic(self, test_domain):
        """When both a type-specific and a generic (database=None) model exist,
        the type-specific model should be used."""

        class Product(BaseAggregate):
            name = String(max_length=100)

        class ProductGenericModel(BaseDatabaseModel):
            name = Text()

        class ProductMemoryModel(BaseDatabaseModel):
            name = Text()

        test_domain.register(Product)
        test_domain.register(ProductGenericModel, part_of=Product)  # database=None
        test_domain.register(ProductMemoryModel, part_of=Product, database="memory")
        test_domain.init(traverse=False)

        repo = test_domain.repository_for(Product)
        # Default test provider is memory, so the memory-specific model wins
        model = repo._database_model
        assert model.meta_.part_of is Product

    def test_generic_model_used_as_fallback(self, test_domain):
        """When only a generic model (database=None) is registered, it should
        be used regardless of the provider's database type."""

        class Widget(BaseAggregate):
            name = String(max_length=100)

        class WidgetGenericModel(BaseDatabaseModel):
            name = Text()

        test_domain.register(Widget)
        test_domain.register(WidgetGenericModel, part_of=Widget)  # database=None
        test_domain.init(traverse=False)

        repo = test_domain.repository_for(Widget)
        model = repo._database_model
        assert model.meta_.part_of is Widget

    def test_nonmatching_model_falls_back_to_auto_construction(self, test_domain):
        """When the only custom model targets a different database, the provider
        should auto-construct a model instead."""

        class Gadget(BaseAggregate):
            name = String(max_length=100)

        class GadgetPostgresModel(BaseDatabaseModel):
            name = Text()

        test_domain.register(Gadget)
        test_domain.register(GadgetPostgresModel, part_of=Gadget, database="postgresql")
        test_domain.init(traverse=False)

        # Default test provider is memory — no memory-specific or generic model
        repo = test_domain.repository_for(Gadget)
        model = repo._database_model
        # Should be an auto-constructed model, not the PostgreSQL one
        assert model is not GadgetPostgresModel
        assert model.meta_.part_of is Gadget

    def test_duplicate_model_for_same_database_raises_error(self, test_domain):
        """Registering two models for the same aggregate and same database
        type should raise IncorrectUsageError."""

        class Invoice(BaseAggregate):
            name = String(max_length=100)

        class InvoiceModel1(BaseDatabaseModel):
            name = Text()

        class InvoiceModel2(BaseDatabaseModel):
            name = Text()

        test_domain.register(Invoice)
        test_domain.register(InvoiceModel1, part_of=Invoice, database="memory")

        with pytest.raises(IncorrectUsageError, match="already registered"):
            test_domain.register(InvoiceModel2, part_of=Invoice, database="memory")
