from protean.core.aggregate import BaseAggregate
from protean.utils import fully_qualified_name


class TestAggregateRegistration:
    def test_manual_registration_of_aggregate(self, test_domain):
        class User(BaseAggregate):
            name: str | None = None

        test_domain.register(User)

        assert fully_qualified_name(User) in test_domain.registry.aggregates

    def test_settings_in_manual_registration(self, test_domain):
        class User(BaseAggregate):
            name: str | None = None

        test_domain.register(User, provider="foobar", database_model="UserModel")

        assert User.meta_.provider == "foobar"
        assert User.meta_.database_model == "UserModel"

    def test_setting_provider_in_decorator_based_registration(self, test_domain):
        @test_domain.aggregate(provider="foobar", database_model="UserModel")
        class User(BaseAggregate):
            name: str | None = None

        assert User.meta_.provider == "foobar"
        assert User.meta_.database_model == "UserModel"

    def test_additional_options_in_decorator_based_registration(self, test_domain):
        @test_domain.aggregate(provider="foobar", database_model="UserModel")
        class Cat:
            name: str | None = None

        assert Cat.meta_.provider == "foobar"
        assert Cat.meta_.database_model == "UserModel"
