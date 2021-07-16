from protean.core.aggregate import BaseAggregate
from protean.core.field.basic import String
from protean.utils import fully_qualified_name


class TestAggregateRegistration:
    def test_manual_registration_of_aggregate(self, test_domain):
        class User(BaseAggregate):
            name = String(max_length=50)

        test_domain.register(User)

        assert fully_qualified_name(User) in test_domain.registry.aggregates

    def test_settings_in_manual_registration(self, test_domain):
        class User(BaseAggregate):
            name = String(max_length=50)

            class Meta:
                provider = "foobar"
                model = "UserModel"

        test_domain.register(User)

        assert User.meta_.provider == "foobar"
        assert User.meta_.model == "UserModel"

    def test_setting_provider_in_decorator_based_registration(self, test_domain):
        @test_domain.aggregate(provider="foobar", model="UserModel")
        class User(BaseAggregate):
            name = String(max_length=50)

        test_domain.register(User)

        assert User.meta_.provider == "foobar"
        assert User.meta_.model == "UserModel"
