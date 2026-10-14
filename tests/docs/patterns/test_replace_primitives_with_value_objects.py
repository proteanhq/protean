"""Run the examples on ``docs/patterns/replace-primitives-with-value-objects.md``."""

from datetime import date

import pytest

from protean import Domain
from protean.exceptions import IncorrectUsageError, ValidationError
from protean.fields import Auto, Float, String
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def in_context(module):
    with module.domain.domain_context():
        yield module


@pytest.fixture
def primitive_user():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/001.py")
    )


@pytest.fixture
def user_with_invariant():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/002.py")
    )


@pytest.fixture
def email_example():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/003.py")
    )


@pytest.fixture
def primitive_product():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/004.py")
    )


@pytest.fixture
def money_example():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/005.py")
    )


@pytest.fixture
def primitive_customer():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/006.py")
    )


@pytest.fixture
def address_example():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/007.py")
    )


@pytest.fixture
def date_range_example():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/008.py")
    )


@pytest.fixture
def order_example():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/009.py")
    )


@pytest.fixture
def percentage_example():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/010.py")
    )


@pytest.fixture
def validation_on_user():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/011.py")
    )


@pytest.fixture
def validation_on_value_objects():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/012.py")
    )


@pytest.fixture
def nested_example():
    yield from in_context(
        load_example("patterns/replace-primitives-with-value-objects/013.py")
    )


ADDRESS = {
    "street": "123 Main St",
    "city": "Springfield",
    "state": "IL",
    "postal_code": "62701",
    "country": "US",
}


class TestThePrimitiveModelsAcceptBadData:
    def test_primitive_user_stores_an_invalid_email(self, primitive_user):
        user = primitive_user.User(name="Jane", email="not-an-email")

        assert user.email == "not-an-email"

    def test_primitive_user_still_requires_an_email(self, primitive_user):
        with pytest.raises(ValidationError) as exc:
            primitive_user.User(name="Jane")

        assert "email" in exc.value.messages

    def test_primitive_product_stores_an_unknown_currency(self, primitive_product):
        product = primitive_product.Product(
            name="Widget",
            price_amount=29.99,
            price_currency="XYZ",
            cost_amount=12.50,
            cost_currency="USD",
        )

        assert product.price_currency == "XYZ"

    def test_primitive_customer_accepts_a_partial_address(self, primitive_customer):
        customer = primitive_customer.Customer(
            name="Jane Smith", shipping_city="Springfield"
        )

        assert customer.shipping_street is None


class TestEmailOnTheAggregate:
    def test_invariant_rejects_an_email_without_at(self, user_with_invariant):
        with pytest.raises(ValidationError) as exc:
            user_with_invariant.User(email="not-an-email")

        assert exc.value.messages == {"email": ["Invalid email address"]}

    def test_invariant_accepts_an_email_with_at(self, user_with_invariant):
        user = user_with_invariant.User(email="user@example.com")

        assert user.email == "user@example.com"


INVALID_EMAILS = ["not-an-email", "@example.com", "user@", "user@example", ""]


class TestEmailValueObject:
    @pytest.mark.parametrize("address", INVALID_EMAILS)
    def test_rejects_an_invalid_address(self, email_example, address):
        with pytest.raises(ValidationError) as exc:
            email_example.Email(address=address)

        assert "address" in exc.value.messages

    def test_rejects_an_address_longer_than_254(self, email_example):
        address = "a" * 250 + "@example.com"

        with pytest.raises(ValidationError) as exc:
            email_example.Email(address=address)

        assert "address" in exc.value.messages

    def test_accepts_a_valid_address(self, email_example):
        email = email_example.Email(address="user@example.com")

        assert email.address == "user@example.com"

    def test_equal_addresses_are_equal(self, email_example):
        assert email_example.Email(address="a@example.com") == email_example.Email(
            address="a@example.com"
        )

    def test_different_addresses_are_not_equal(self, email_example):
        assert email_example.Email(address="a@example.com") != email_example.Email(
            address="b@example.com"
        )

    def test_user_holds_a_valid_email(self, email_example):
        user = email_example.User(email=email_example.Email(address="user@example.com"))

        assert user.email.address == "user@example.com"

    def test_user_requires_an_email(self, email_example):
        with pytest.raises(ValidationError) as exc:
            email_example.User()

        assert "email" in exc.value.messages

    def test_usage_signs_up_the_valid_email(self, email_example):
        user = email_example.sign_up_valid_user()

        assert user.email == email_example.Email(address="user@example.com")

    def test_usage_raises_at_the_invalid_email(self, email_example):
        with pytest.raises(ValidationError) as exc:
            email_example.sign_up_invalid_user()

        assert exc.value.messages == {"address": ["Must be a valid email address"]}

    def test_assigning_a_field_raises_incorrect_usage(self, email_example):
        with pytest.raises(IncorrectUsageError):
            email_example.change_email()

    def test_a_new_value_object_is_not_blocked(self, email_example):
        email = email_example.Email(address="user@example.com")
        replacement = email_example.Email(address="other@example.com")

        assert email.address == "user@example.com"
        assert replacement.address == "other@example.com"


class TestMoneyValueObject:
    def test_rejects_a_negative_amount(self, money_example):
        with pytest.raises(ValidationError) as exc:
            money_example.Money(amount=-1.0, currency="USD")

        assert exc.value.messages == {"amount": ["Amount cannot be negative"]}

    @pytest.mark.parametrize("currency", ["XYZ", "usd", "US"])
    def test_rejects_an_unknown_currency(self, money_example, currency):
        with pytest.raises(ValidationError) as exc:
            money_example.Money(amount=1.0, currency=currency)

        assert "currency" in exc.value.messages

    @pytest.mark.parametrize("currency", ["USD", "EUR", "GBP", "JPY", "CAD", "AUD"])
    def test_accepts_a_listed_currency(self, money_example, currency):
        assert money_example.Money(amount=0.0, currency=currency).currency == currency

    def test_equal_fields_are_equal(self, money_example):
        assert money_example.money1 == money_example.money2
        assert money_example.Money(amount=100.0, currency="USD") == money_example.Money(
            amount=100.0, currency="USD"
        )

    @pytest.mark.parametrize(
        "other",
        [{"amount": 101.0, "currency": "USD"}, {"amount": 100.0, "currency": "EUR"}],
    )
    def test_a_different_field_is_not_equal(self, money_example, other):
        assert money_example.Money(amount=100.0, currency="USD") != money_example.Money(
            **other
        )

    def test_add_same_currency(self, money_example):
        total = money_example.Money(amount=10.0, currency="USD").add(
            money_example.Money(amount=5.0, currency="USD")
        )

        assert total == money_example.Money(amount=15.0, currency="USD")

    def test_add_different_currencies_raises(self, money_example):
        with pytest.raises(ValidationError) as exc:
            money_example.Money(amount=10.0, currency="USD").add(
                money_example.Money(amount=5.0, currency="EUR")
            )

        assert exc.value.messages == {"currency": ["Cannot add different currencies"]}

    def test_subtract_below_zero_raises(self, money_example):
        with pytest.raises(ValidationError) as exc:
            money_example.Money(amount=5.0, currency="USD").subtract(
                money_example.Money(amount=10.0, currency="USD")
            )

        assert exc.value.messages == {"amount": ["Amount cannot be negative"]}

    def test_multiply(self, money_example):
        doubled = money_example.Money(amount=10.0, currency="GBP").multiply(2)

        assert doubled == money_example.Money(amount=20.0, currency="GBP")

    def test_widget_margin(self, money_example):
        margin = money_example.widget_margin()

        assert margin.amount == pytest.approx(17.49)
        assert margin.currency == "USD"

    def test_mixed_currency_margin_raises(self, money_example):
        with pytest.raises(ValidationError) as exc:
            money_example.mixed_currency_margin()

        assert exc.value.messages == {
            "currency": ["Cannot subtract different currencies"]
        }


class TestAddressValueObject:
    @pytest.mark.parametrize("country", ["USA", "U1", "1S", "u"])
    def test_rejects_a_non_iso_country(self, address_example, country):
        with pytest.raises(ValidationError) as exc:
            address_example.Address(**{**ADDRESS, "country": country})

        assert "country" in exc.value.messages

    @pytest.mark.parametrize("missing", ["street", "city", "state", "postal_code"])
    def test_rejects_a_partial_address(self, address_example, missing):
        fields = {key: value for key, value in ADDRESS.items() if key != missing}

        with pytest.raises(ValidationError) as exc:
            address_example.Address(**fields)

        assert missing in exc.value.messages

    def test_equal_fields_are_equal(self, address_example):
        assert address_example.Address(**ADDRESS) == address_example.Address(**ADDRESS)

    def test_a_different_field_is_not_equal(self, address_example):
        assert address_example.Address(**ADDRESS) != address_example.Address(
            **{**ADDRESS, "postal_code": "62702"}
        )

    def test_register_customer(self, address_example):
        customer = address_example.register_customer()

        assert customer.shipping_address.city == "Springfield"
        assert customer.billing_address.city == "Chicago"

    def test_move_customer_replaces_the_address(self, address_example):
        customer = address_example.register_customer()

        address_example.move_customer(customer)

        assert customer.shipping_address == address_example.Address(
            street="789 Pine St",
            city="Oakland",
            state="CA",
            postal_code="94607",
            country="US",
        )
        assert customer.billing_address.city == "Chicago"


class TestDateRangeValueObject:
    @pytest.mark.parametrize("end", [date(2026, 1, 1), date(2025, 12, 31)])
    def test_rejects_an_end_not_after_start(self, date_range_example, end):
        with pytest.raises(ValidationError) as exc:
            date_range_example.DateRange(start_date=date(2026, 1, 1), end_date=end)

        assert exc.value.messages == {"end_date": ["End date must be after start date"]}

    def test_equal_fields_are_equal(self, date_range_example):
        DateRange = date_range_example.DateRange

        assert DateRange(
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        ) == DateRange(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

    def test_a_different_field_is_not_equal(self, date_range_example):
        DateRange = date_range_example.DateRange

        assert DateRange(
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
        ) != DateRange(start_date=date(2026, 1, 1), end_date=date(2026, 2, 1))

    def test_operations(self, date_range_example):
        DateRange = date_range_example.DateRange
        january = DateRange(start_date=date(2026, 1, 1), end_date=date(2026, 1, 31))

        assert january.duration_days() == 30
        assert january.contains(date(2026, 1, 15))
        assert not january.contains(date(2026, 2, 1))
        assert january.overlaps(
            DateRange(start_date=date(2026, 1, 31), end_date=date(2026, 2, 28))
        )
        assert not january.overlaps(
            DateRange(start_date=date(2026, 2, 1), end_date=date(2026, 2, 28))
        )

    def test_campaign_is_active_on(self, date_range_example):
        campaign = date_range_example.Campaign(
            name="Winter sale",
            active_period=date_range_example.DateRange(
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 31)
            ),
        )

        assert campaign.is_active_on(date(2026, 1, 31))
        assert not campaign.is_active_on(date(2026, 2, 1))


class TestValueObjectField:
    def test_order_embeds_the_value_objects(self, order_example):
        order = order_example.Order(
            total=order_example.Money(amount=10.0, currency="USD"),
            shipping_address=order_example.Address(**ADDRESS),
        )

        assert order.total.amount == 10.0
        assert order.shipping_address.city == "Springfield"

    def test_order_requires_a_total(self, order_example):
        with pytest.raises(ValidationError) as exc:
            order_example.Order()

        assert "total" in exc.value.messages


class TestNoIdentityAllowed:
    def test_identifier_field_on_a_value_object_raises(self):
        domain = Domain(name="ValueObjectWithIdentity")

        with pytest.raises(IncorrectUsageError):

            @domain.value_object
            class Money:
                id: Auto(identifier=True)
                amount: Float()
                currency: String()


class TestPercentageValueObject:
    @pytest.mark.parametrize("value", [-0.1, 100.1])
    def test_rejects_a_value_outside_zero_to_hundred(self, percentage_example, value):
        with pytest.raises(ValidationError) as exc:
            percentage_example.Percentage(value=value)

        assert exc.value.messages == {"value": ["Percentage must be between 0 and 100"]}

    @pytest.mark.parametrize("value", [0.0, 50.0, 100.0])
    def test_accepts_a_value_in_range(self, percentage_example, value):
        assert percentage_example.Percentage(value=value).value == value

    def test_equality(self, percentage_example):
        Percentage = percentage_example.Percentage

        assert Percentage(value=10.0) == Percentage(value=10.0)
        assert Percentage(value=10.0) != Percentage(value=20.0)


class TestTheValidationShift:
    @pytest.mark.parametrize(
        ("fields", "key"),
        [({"email": "bad"}, "email"), ({"email": "a@b.c", "phone": "12ab"}, "phone")],
    )
    def test_before_the_user_rejects_bad_values(self, validation_on_user, fields, key):
        with pytest.raises(ValidationError) as exc:
            validation_on_user.User(**fields)

        assert key in exc.value.messages

    def test_before_the_user_accepts_good_values(self, validation_on_user):
        user = validation_on_user.User(email="a@b.c", phone="+1-555-0100")

        assert user.phone == "+1-555-0100"

    def test_after_email_rejects_a_bad_address(self, validation_on_value_objects):
        with pytest.raises(ValidationError) as exc:
            validation_on_value_objects.Email(address="bad")

        assert exc.value.messages == {"address": ["Invalid email"]}

    @pytest.mark.parametrize("number", ["12ab", "phone", "+1-555-01x0"])
    def test_after_phone_rejects_a_bad_number(
        self, validation_on_value_objects, number
    ):
        with pytest.raises(ValidationError) as exc:
            validation_on_value_objects.Phone(number=number)

        assert exc.value.messages == {"number": ["Invalid phone number"]}

    def test_after_phone_accepts_spaces_and_dashes(self, validation_on_value_objects):
        phone = validation_on_value_objects.Phone(number="+1 555-0100")

        assert phone.number == "+1 555-0100"

    def test_after_value_objects_compare_by_value(self, validation_on_value_objects):
        Email = validation_on_value_objects.Email
        Phone = validation_on_value_objects.Phone

        assert Email(address="a@b.c") == Email(address="a@b.c")
        assert Email(address="a@b.c") != Email(address="x@b.c")
        assert Phone(number="555") == Phone(number="555")
        assert Phone(number="555") != Phone(number="556")

    def test_after_user_needs_no_invariants(self, validation_on_value_objects):
        module = validation_on_value_objects
        user = module.User(
            email=module.Email(address="a@b.c"), phone=module.Phone(number="555")
        )

        assert user.phone.number == "555"


class TestNestedValueObjects:
    @pytest.mark.parametrize(
        ("latitude", "longitude", "key"),
        [(90.1, 0.0, "latitude"), (-90.1, 0.0, "latitude"), (0.0, 180.1, "longitude")],
    )
    def test_rejects_out_of_range_coordinates(
        self, nested_example, latitude, longitude, key
    ):
        with pytest.raises(ValidationError) as exc:
            nested_example.GeoLocation(latitude=latitude, longitude=longitude)

        assert key in exc.value.messages

    def test_equality(self, nested_example):
        GeoLocation = nested_example.GeoLocation

        assert GeoLocation(latitude=1.0, longitude=2.0) == GeoLocation(
            latitude=1.0, longitude=2.0
        )
        assert GeoLocation(latitude=1.0, longitude=2.0) != GeoLocation(
            latitude=1.0, longitude=3.0
        )

    def test_address_holds_an_optional_location(self, nested_example):
        location = nested_example.GeoLocation(latitude=39.8, longitude=-89.6)

        with_location = nested_example.Address(**ADDRESS, location=location)
        without_location = nested_example.Address(**ADDRESS)

        assert with_location.location == location
        assert without_location.location is None
        assert with_location != without_location
