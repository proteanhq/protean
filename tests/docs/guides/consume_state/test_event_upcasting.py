"""Run the examples on ``docs/guides/consume-state/event-upcasting.md``."""

import pytest

from protean.core.upcaster import BaseUpcaster
from protean.exceptions import (
    ConfigurationError,
    DeserializationError,
    ValidationError,
)
from protean.utils.eventing import Message
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _metadata(type_string: str, version: int, stream: str) -> dict:
    return {
        "headers": {
            "id": f"msg-{version}",
            "type": type_string,
            "time": "2025-01-01T00:00:00+00:00",
            "stream": stream,
        },
        "envelope": {"specversion": "1.0"},
        "domain": {
            "kind": "EVENT",
            "stream_category": stream.rsplit("-", 1)[0],
            "version": version,
            "sequence_id": "0",
            "asynchronous": True,
        },
    }


def _read(type_string: str, version: int, data: dict):
    """Read a stored payload back as a typed event, the way a handler gets it."""
    raw = {"data": data, "metadata": _metadata(type_string, version, "test::x-1")}
    return Message.deserialize(raw, validate=False).to_domain_object()


@pytest.fixture
def currency():
    example = load_example("guides/consume-state/event-upcasting/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def before():
    example = load_example("guides/consume-state/event-upcasting/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def customers():
    example = load_example("guides/consume-state/event-upcasting/003.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def chain():
    example = load_example("guides/consume-state/event-upcasting/004.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def removed_field():
    example = load_example("guides/consume-state/event-upcasting/005.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def derived_field():
    example = load_example("guides/consume-state/event-upcasting/006.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


class TestAddingARequiredField:
    def test_the_v1_event_has_no_currency(self, before):
        assert before.OrderPlaced.__version__ == 1
        with pytest.raises(ValidationError) as exc:
            before.OrderPlaced(order_id="o-1", amount=42.0, currency="USD")
        assert "currency" in exc.value.messages

    def test_a_stored_v1_event_reads_with_usd(self, currency):
        event = _read("Ordering.OrderPlaced.v1", 1, {"order_id": "o-1", "amount": 42.0})

        assert isinstance(event, currency.OrderPlaced)
        assert event.order_id == "o-1"
        assert event.amount == 42.0
        assert event.currency == "USD"

    def test_a_stored_v2_event_keeps_its_currency(self, currency):
        event = _read(
            "Ordering.OrderPlaced.v2",
            2,
            {"order_id": "o-1", "amount": 42.0, "currency": "EUR"},
        )

        assert event.currency == "EUR"


class TestSplittingAndNestingCustomerFields:
    def test_a_stored_v1_event_reads_in_the_v3_shape(self, customers):
        event = _read(
            "Customers.CustomerRegistered.v1",
            1,
            {
                "customer_id": "c-1",
                "customer_name": "Ada Lovelace",
                "street": "12 St James's Square",
                "city": "London",
                "state": "LDN",
                "zip_code": "SW1Y 4LB",
            },
        )

        assert isinstance(event, customers.CustomerRegistered)
        assert event.first_name == "Ada"
        assert event.last_name == "Lovelace"
        assert event.address == customers.Address(
            street="12 St James's Square",
            city="London",
            state="LDN",
            zip_code="SW1Y 4LB",
        )

    def test_a_one_word_name_leaves_the_last_name_empty(self, customers):
        upcast = customers.UpcastCustomerRegisteredV1ToV2().upcast(
            {"customer_id": "c-1", "customer_name": "Ada"}
        )

        assert upcast == {"customer_id": "c-1", "first_name": "Ada", "last_name": ""}

    def test_a_name_of_three_words_keeps_the_last_two_as_the_last_name(self, customers):
        upcast = customers.UpcastCustomerRegisteredV1ToV2().upcast(
            {"customer_id": "c-1", "customer_name": "Mary Ann Evans"}
        )

        assert upcast["first_name"] == "Mary"
        assert upcast["last_name"] == "Ann Evans"

    def test_a_stored_v1_event_without_a_name_fails_and_names_the_field(
        self, customers
    ):
        with pytest.raises(DeserializationError, match="customer_name"):
            _read("Customers.CustomerRegistered.v1", 1, {"customer_id": "c-1"})

    def test_a_missing_address_part_becomes_an_empty_string(self, customers):
        event = _read(
            "Customers.CustomerRegistered.v2",
            2,
            {"customer_id": "c-1", "first_name": "Ada", "city": "London"},
        )

        assert event.address == customers.Address(
            street="", city="London", state="", zip_code=""
        )

    def test_a_stored_v2_event_only_nests_the_address(self, customers):
        event = _read(
            "Customers.CustomerRegistered.v2",
            2,
            {
                "customer_id": "c-1",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "street": "12 St James's Square",
                "city": "London",
                "state": "LDN",
                "zip_code": "SW1Y 4LB",
            },
        )

        assert event.first_name == "Ada"
        assert event.address.city == "London"


class TestMultiStepChain:
    def test_a_stored_v1_event_passes_through_both_upcasters(self, chain):
        event = _read("Ordering.OrderPlaced.v1", 1, {"order_id": "1", "amount": 100})

        assert isinstance(event, chain.OrderPlaced)
        assert event.total_amount == 100.0
        assert event.currency == "USD"

    def test_a_stored_v2_event_passes_through_only_the_second(self, chain):
        event = _read(
            "Ordering.OrderPlaced.v2",
            2,
            {"order_id": "1", "amount": 100, "currency": "EUR"},
        )

        assert event.total_amount == 100.0
        assert event.currency == "EUR"

    def test_a_stored_v3_event_is_read_as_is(self, chain):
        event = _read(
            "Ordering.OrderPlaced.v3",
            3,
            {"order_id": "1", "total_amount": 50, "currency": "EUR"},
        )

        assert event.total_amount == 50.0
        assert event.currency == "EUR"

    def test_a_stored_v1_event_without_an_amount_fails_and_names_the_field(self, chain):
        with pytest.raises(DeserializationError, match="amount"):
            _read("Ordering.OrderPlaced.v1", 1, {"order_id": "1"})

    def test_an_event_sourced_order_replays_a_v1_event(self, chain):
        stream = f"{chain.Order.meta_.stream_category}-1"
        chain.domain.event_store.store._write(
            stream,
            "Ordering.OrderPlaced.v1",
            {"order_id": "1", "amount": 100},
            _metadata("Ordering.OrderPlaced.v1", 1, stream),
            -1,
        )

        order = chain.domain.repository_for(chain.Order).get("1")

        assert order.order_id == "1"
        assert order.total_amount == 100.0
        assert order.currency == "USD"

    def test_the_event_handler_receives_the_current_schema(self, chain):
        raw = {
            "data": {"order_id": "1", "amount": 100},
            "metadata": _metadata("Ordering.OrderPlaced.v1", 1, "test::x-1"),
        }
        chain.revenue_by_currency.clear()

        chain.AnalyticsHandler._handle(Message.deserialize(raw, validate=False))

        assert chain.revenue_by_currency == {"USD": 100.0}


class TestRemovingAndDerivingFields:
    def test_the_current_event_rejects_the_obsolete_field(self, removed_field):
        with pytest.raises(ValidationError) as exc:
            removed_field.OrderPlaced(order_id="o-1", amount=10.0, legacy_code="X1")
        assert "legacy_code" in exc.value.messages

    def test_a_stored_v1_event_drops_the_obsolete_field(self, removed_field):
        event = _read(
            "Ordering.OrderPlaced.v1",
            1,
            {"order_id": "o-1", "amount": 10.0, "legacy_code": "X1"},
        )

        assert event.order_id == "o-1"
        assert event.amount == 10.0
        assert not hasattr(event, "legacy_code")

    def test_a_stored_v1_event_gets_a_line_item_count(self, derived_field):
        items = [{"sku": "A", "qty": 1}, {"sku": "B", "qty": 3}]
        event = _read("Ordering.OrderPlaced.v1", 1, {"order_id": "o-1", "items": items})

        assert event.items == items
        assert event.line_item_count == 2

    def test_the_count_follows_the_number_of_items(self, derived_field):
        items = [{"sku": "A"}, {"sku": "B"}, {"sku": "C"}]
        event = _read("Ordering.OrderPlaced.v1", 1, {"order_id": "o-1", "items": items})

        assert event.line_item_count == 3

    def test_a_stored_v1_event_without_items_counts_zero(self, derived_field):
        event = _read("Ordering.OrderPlaced.v1", 1, {"order_id": "o-1"})

        assert event.line_item_count == 0


class TestValidationAtStartup:
    def test_a_duplicate_upcaster_is_rejected(self):
        example = load_example("guides/consume-state/event-upcasting/001.py")

        @example.domain.upcaster(
            event_type=example.OrderPlaced, from_version=1, to_version=2
        )
        class UpcasterB(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                return data

        with pytest.raises(
            ConfigurationError,
            match="Duplicate upcaster for `Ordering.OrderPlaced` from version `1`",
        ):
            example.domain.init(traverse=False)

    def test_a_version_cycle_is_rejected(self):
        example = load_example("guides/consume-state/event-upcasting/001.py")

        @example.domain.upcaster(
            event_type=example.OrderPlaced, from_version=2, to_version=1
        )
        class Backward(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                return data

        with pytest.raises(ConfigurationError, match="does not converge"):
            example.domain.init(traverse=False)

    def test_two_terminal_versions_are_rejected(self):
        example = load_example("guides/consume-state/event-upcasting/001.py")

        @example.domain.upcaster(
            event_type=example.OrderPlaced, from_version=3, to_version=4
        )
        class BranchB(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                return data

        with pytest.raises(
            ConfigurationError, match="does not converge to a single current version"
        ):
            example.domain.init(traverse=False)

    def test_a_chain_ending_at_an_unknown_version_is_rejected(self):
        example = load_example("guides/consume-state/event-upcasting/002.py")

        @example.domain.upcaster(
            event_type=example.OrderPlaced, from_version=1, to_version=99
        )
        class WrongTarget(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                return data

        with pytest.raises(
            ConfigurationError,
            match="no event is registered with type string `Ordering.OrderPlaced.v99`",
        ):
            example.domain.init(traverse=False)
