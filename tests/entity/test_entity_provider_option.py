import pytest

from protean import BaseAggregate, BaseEntity
from protean.exceptions import IncorrectUsageError
from protean.fields import HasOne, Integer, String


class Department(BaseAggregate):
    name = String(max_length=50)
    dean = HasOne("Dean")


class Dean(BaseEntity):
    name = String(max_length=50)
    age = Integer(min_value=21)


class TestAggregateAndEntityDefaultProvider:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Department)
        test_domain.register(Dean, part_of=Department)

    def test_default_provider_is_none(self, test_domain):
        test_domain.init(traverse=False)

        assert Department.meta_.provider == "default"
        assert Dean.meta_.provider == "default"


class TestWhenEntityHasSameProviderAsAggregate:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Department, provider="primary")
        test_domain.register(Dean, part_of=Department, provider="primary")

    def test_entity_provider_is_same_as_aggregate_provider(self, test_domain):
        test_domain.init(traverse=False)

        assert Department.meta_.provider == "primary"
        assert Dean.meta_.provider == "primary"


class TestWhenEntityDoesNotHaveSameProviderAsAggregate:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Department, provider="primary")
        test_domain.register(Dean, part_of=Department, provider="secondary")

    def test_entity_provider_is_same_as_aggregate_provider(self, test_domain):
        with pytest.raises(IncorrectUsageError) as exc:
            test_domain.init(traverse=False)

        assert exc.value.messages == {
            "element": "Entity `Dean` has a different provider than its aggregate `Department`"
        }
