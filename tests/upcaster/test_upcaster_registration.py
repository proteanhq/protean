"""Tests for upcaster registration and validation."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.upcaster import BaseUpcaster
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import Float, Identifier, String


# ── Domain elements used across tests ────────────────────────────────────


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    status = String(default="draft")


class OrderPlaced(BaseEvent):
    __version__ = "v2"
    order_id = Identifier(required=True)
    amount = Float(required=True)
    currency = String(default="USD")


class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


# ── Registration tests ───────────────────────────────────────────────────


class TestUpcasterRegistration:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.upcaster(
            UpcastOrderPlacedV1ToV2,
            event_type=OrderPlaced,
            from_version="v1",
            to_version="v2",
        )
        test_domain.init(traverse=False)

    def test_upcaster_is_registered(self, test_domain):
        assert len(test_domain._upcasters) == 1

    def test_upcaster_meta_options(self, test_domain):
        upcaster_cls = test_domain._upcasters[0]
        assert upcaster_cls.meta_.event_type is OrderPlaced
        assert upcaster_cls.meta_.from_version == "v1"
        assert upcaster_cls.meta_.to_version == "v2"

    def test_upcaster_chain_is_built(self, test_domain):
        assert test_domain._upcaster_chain.needs_upcasting("Test.OrderPlaced.v1")

    def test_upcaster_chain_resolves_to_current_class(self, test_domain):
        resolved = test_domain._upcaster_chain.resolve_event_class(
            "Test.OrderPlaced.v1"
        )
        assert resolved is OrderPlaced


class TestUpcasterRegistrationWithDecorator:
    def test_decorator_with_options(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlaced, part_of=Order)

        @test_domain.upcaster(
            event_type=OrderPlaced, from_version="v1", to_version="v2"
        )
        class MyUpcaster(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                data["currency"] = "USD"
                return data

        test_domain.init(traverse=False)

        assert len(test_domain._upcasters) == 1
        assert test_domain._upcaster_chain.needs_upcasting("Test.OrderPlaced.v1")


# ── Validation tests ─────────────────────────────────────────────────────


class TestUpcasterValidation:
    def test_error_missing_event_type(self, test_domain):
        with pytest.raises(IncorrectUsageError, match="must specify `event_type`"):
            test_domain.upcaster(
                UpcastOrderPlacedV1ToV2,
                from_version="v1",
                to_version="v2",
            )

    def test_error_missing_from_version(self, test_domain):
        with pytest.raises(IncorrectUsageError, match="must specify `from_version`"):
            test_domain.upcaster(
                UpcastOrderPlacedV1ToV2,
                event_type=OrderPlaced,
                to_version="v2",
            )

    def test_error_missing_to_version(self, test_domain):
        with pytest.raises(IncorrectUsageError, match="must specify `to_version`"):
            test_domain.upcaster(
                UpcastOrderPlacedV1ToV2,
                event_type=OrderPlaced,
                from_version="v1",
            )

    def test_error_same_from_and_to_version(self, test_domain):
        with pytest.raises(
            IncorrectUsageError, match="from_version and to_version must differ"
        ):
            test_domain.upcaster(
                UpcastOrderPlacedV1ToV2,
                event_type=OrderPlaced,
                from_version="v1",
                to_version="v1",
            )

    def test_error_event_type_not_an_event(self, test_domain):
        with pytest.raises(IncorrectUsageError, match="must be an Event class"):
            test_domain.upcaster(
                UpcastOrderPlacedV1ToV2,
                event_type=Order,  # Not an event!
                from_version="v1",
                to_version="v2",
            )

    def test_base_upcaster_cannot_be_instantiated(self):
        with pytest.raises(NotSupportedError):
            BaseUpcaster()
