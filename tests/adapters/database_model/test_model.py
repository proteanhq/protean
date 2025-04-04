import pytest

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
