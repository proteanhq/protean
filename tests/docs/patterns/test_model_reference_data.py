"""Run the examples on ``docs/patterns/model-reference-data.md``."""

import pytest

from protean.exceptions import ObjectNotFoundError, ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def choices():
    module = load_example("patterns/model-reference-data/001.py")
    with module.domain.domain_context():
        yield module


@pytest.fixture
def enumeration():
    module = load_example("patterns/model-reference-data/002.py")
    with module.domain.domain_context():
        yield module


@pytest.fixture
def currencies():
    module = load_example("patterns/model-reference-data/003.py")
    with module.domain.domain_context():
        module.seed_currencies()
        yield module


class TestFieldChoices:
    def test_status_defaults_to_draft(self, choices):
        assert choices.Order().status == "draft"

    def test_a_listed_status_is_accepted(self, choices):
        assert choices.Order(status="shipped").status == "shipped"

    def test_an_unlisted_status_is_rejected(self, choices):
        with pytest.raises(ValidationError) as exc:
            choices.Order(status="teleported")

        assert "status" in exc.value.messages


class TestEnumerationValueObject:
    def test_of_looks_up_the_label(self, enumeration):
        status = enumeration.OrderStatus.of("placed")

        assert (status.code, status.label) == ("placed", "Placed")

    def test_of_an_unknown_code_finds_nothing(self, enumeration):
        with pytest.raises(KeyError):
            enumeration.OrderStatus.of("teleported")

    def test_all_lists_the_registry_in_order(self, enumeration):
        statuses = enumeration.OrderStatus.all()

        assert statuses
        assert [s.code for s in statuses] == ["draft", "placed", "shipped", "delivered"]
        assert [s.label for s in statuses] == [
            "Draft",
            "Placed",
            "Shipped",
            "Delivered",
        ]

    def test_a_valid_order_holds_the_status(self, enumeration):
        order = enumeration.valid_order()

        assert order.status == enumeration.OrderStatus(code="placed", label="Placed")

    def test_an_unknown_status_fails_at_construction(self, enumeration):
        with pytest.raises(ValidationError) as exc:
            enumeration.invalid_order()

        assert exc.value.messages["code"] == ["Unknown order status: teleported"]


class TestCurrencyAggregate:
    def test_the_seeded_code_loads_its_currency(self, currencies):
        usd = currencies.find_usd()

        assert (usd.code, usd.name, usd.symbol, usd.minor_units) == (
            "USD",
            "US Dollar",
            "$",
            2,
        )

    def test_the_seed_keeps_each_currency_s_own_fields(self, currencies):
        jpy = currencies.domain.repository_for(currencies.Currency).get("JPY")

        assert jpy.minor_units == 0

    def test_an_unknown_code_is_not_found(self, currencies):
        repo = currencies.domain.repository_for(currencies.Currency)

        with pytest.raises(ObjectNotFoundError):
            repo.get("GBP")

    @pytest.mark.parametrize("code", ["U5D", "usd", "ÉUR"])
    def test_a_code_that_is_not_three_letters_is_rejected(self, currencies, code):
        with pytest.raises(ValidationError) as exc:
            currencies.Currency(code=code, name="Bad")

        assert exc.value.messages["code"] == [
            "Currency code must be a 3-letter ISO 4217 code"
        ]

    def test_deactivate_raises_currency_deactivated(self, currencies):
        usd = currencies.find_usd()

        usd.deactivate()

        assert usd.is_active is False
        assert len(usd._events) == 1
        assert isinstance(usd._events[0], currencies.CurrencyDeactivated)
        assert usd._events[0].code == "USD"


class TestCurrencyRepository:
    def deactivate(self, module, code):
        repo = module.domain.repository_for(module.Currency)
        currency = repo.get(code)
        currency.deactivate()
        repo.add(currency)

    def test_the_repository_is_the_custom_one(self, currencies):
        repo = currencies.domain.repository_for(currencies.Currency)

        assert isinstance(repo, currencies.CurrencyRepository)

    def test_the_dropdown_lists_every_active_currency(self, currencies):
        codes = {c.code for c in currencies.currency_dropdown()}

        assert codes == {"USD", "EUR", "JPY"}

    def test_the_dropdown_leaves_out_a_deactivated_currency(self, currencies):
        self.deactivate(currencies, "JPY")

        codes = {c.code for c in currencies.currency_dropdown()}

        assert codes == {"USD", "EUR"}

    def test_the_map_is_keyed_by_code(self, currencies):
        repo = currencies.domain.repository_for(currencies.Currency)

        by_code = repo.as_map()

        assert set(by_code) == {"USD", "EUR", "JPY"}
        assert by_code["EUR"].name == "Euro"

    def test_a_known_code_validates(self, currencies):
        assert currencies.validate_currency("EUR").symbol == "€"

    def test_an_unknown_code_fails_validation(self, currencies):
        with pytest.raises(ValidationError) as exc:
            currencies.validate_currency("GBP")

        assert exc.value.messages["currency"] == ["Unknown currency"]

    def test_a_deactivated_code_fails_validation(self, currencies):
        self.deactivate(currencies, "EUR")

        with pytest.raises(ValidationError):
            currencies.validate_currency("EUR")
