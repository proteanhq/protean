import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import IncorrectUsageError
from protean.fields import HasOne, Integer, String


class Department(BaseAggregate):
    name: String(max_length=50)
    dean = HasOne("Dean")


class Dean(BaseEntity):
    name: String(max_length=50)
    age: Integer(min_value=21)


class TestAggregateAndEntityDefaultProvider:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Department)
        test_domain.register(Dean, part_of=Department)

    def test_default_provider_is_none(self, test_domain):
        test_domain.init(traverse=False)

        assert Department.meta_.database == "default"
        assert Dean.meta_.database == "default"


class TestWhenEntityHasSameProviderAsAggregate:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Department, database="primary")
        test_domain.register(Dean, part_of=Department, database="primary")

    def test_entity_provider_is_same_as_aggregate_provider(self, test_domain):
        test_domain.init(traverse=False)

        assert Department.meta_.database == "primary"
        assert Dean.meta_.database == "primary"


class TestWhenEntityDoesNotHaveSameProviderAsAggregate:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Department, database="primary")
        test_domain.register(Dean, part_of=Department, database="secondary")

    def test_entity_provider_is_same_as_aggregate_provider(self, test_domain):
        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert (
            exc.value.args[0]
            == "Entity `Dean` has a different database than its aggregate `Department`"
        )
