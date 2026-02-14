import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import Text
from protean.utils import fully_qualified_name


class Person(BaseAggregate):
    name: str | None = None


class PersonModel(BaseDatabaseModel):
    name = Text()


class TestDatabaseModelInitialization:
    def test_base_database_model_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError) as exception:
            BaseDatabaseModel()
        assert str(exception.value) == "BaseDatabaseModel cannot be instantiated"

    def test_database_model_should_be_associated_with_an_aggregate_or_entity(
        self, test_domain
    ):
        test_domain.register(Person)

        with pytest.raises(IncorrectUsageError) as exception:
            test_domain.register(PersonModel)
        assert (
            str(exception.value)
            == "Database Model `PersonModel` should be associated with an Entity or Aggregate"
        )

    def test_database_model_can_be_registered_with_domain(self, test_domain):
        test_domain.register(Person)
        test_domain.register(PersonModel, part_of=Person)

        # Check that model is registered with domain
        assert fully_qualified_name(PersonModel) in test_domain.registry.database_models
