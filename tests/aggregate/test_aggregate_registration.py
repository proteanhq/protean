import pytest

from protean.core.aggregate import BaseAggregate
from protean.exceptions import ConfigurationError
from protean.fields import String
from protean.utils import _fully_qualified_name


class TestAggregateRegistration:
    def test_manual_registration_of_aggregate(self, test_domain):
        class User(BaseAggregate):
            name: String(max_length=50)

        test_domain.register(User)

        assert _fully_qualified_name(User) in test_domain.registry.aggregates

    def test_settings_in_manual_registration(self, test_domain):
        class User(BaseAggregate):
            name: String(max_length=50)

        test_domain.register(User, provider="foobar")

        assert User.meta_.provider == "foobar"
        assert "database_model" not in dict(User.meta_)

    def test_setting_provider_in_decorator_based_registration(self, test_domain):
        @test_domain.aggregate(provider="foobar")
        class User(BaseAggregate):
            name: String(max_length=50)

        assert User.meta_.provider == "foobar"

    def test_additional_options_in_decorator_based_registration(self, test_domain):
        @test_domain.aggregate(provider="foobar")
        class Cat:
            name: String(max_length=50)

        assert Cat.meta_.provider == "foobar"


class TestDatabaseModelOptionIsRejected:
    """A custom model is registered with ``@domain.database_model(part_of=...)``.

    Aggregates take no ``database_model`` option, so passing one raises instead
    of being silently ignored.
    """

    def test_manual_registration_with_database_model_raises(self, test_domain):
        class User(BaseAggregate):
            name: String(max_length=50)

        with pytest.raises(ConfigurationError) as exc:
            test_domain.register(User, database_model="UserModel")

        assert "Unknown option" in str(exc.value)
        assert "database_model" in str(exc.value)

    def test_decorator_registration_with_database_model_raises(self, test_domain):
        with pytest.raises(ConfigurationError) as exc:

            @test_domain.aggregate(provider="foobar", database_model="UserModel")
            class User:
                name: String(max_length=50)

        assert "Unknown option" in str(exc.value)
        assert "database_model" in str(exc.value)
