import pytest

from protean.core.aggregate import BaseAggregate
from protean.fields import Integer, String

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
