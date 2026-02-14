import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.exceptions import IncorrectUsageError
from protean.fields import HasOne


class Department(BaseAggregate):
    name: str | None = None
    dean = HasOne("Dean")


class Dean(BaseEntity):
    name: str | None = None
    age: int | None = None


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

        assert (
            exc.value.args[0]
            == "Entity `Dean` has a different provider than its aggregate `Department`"
        )
