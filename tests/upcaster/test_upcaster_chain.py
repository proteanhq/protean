"""Tests for upcaster chain building and validation."""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.upcaster import BaseUpcaster
from protean.exceptions import ConfigurationError
from protean.fields import Float, Identifier, String


# ── Domain elements ──────────────────────────────────────────────────────


class Order(BaseAggregate):
    order_id = Identifier(identifier=True)
    status = String(default="draft")


# ── Events at different version stages ───────────────────────────────────


class OrderPlacedV3(BaseEvent):
    """Current version of OrderPlaced."""

    __version__ = "v3"
    order_id = Identifier(required=True)
    total_amount = Float(required=True)
    currency = String(required=True)


class OrderShipped(BaseEvent):
    """Single-hop upcasting target (v2)."""

    __version__ = "v2"
    order_id = Identifier(required=True)
    tracking_number = String(required=True)
    carrier = String(default="unknown")


# ── Upcasters ────────────────────────────────────────────────────────────


class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["currency"] = "USD"
        return data


class UpcastOrderPlacedV2ToV3(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["total_amount"] = data.pop("amount")
        return data


class UpcastOrderShippedV1ToV2(BaseUpcaster):
    def upcast(self, data: dict) -> dict:
        data["carrier"] = "unknown"
        return data


# ── Happy path tests ─────────────────────────────────────────────────────


class TestSingleStepChain:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderShipped, part_of=Order)
        test_domain.upcaster(
            UpcastOrderShippedV1ToV2,
            event_type=OrderShipped,
            from_version="v1",
            to_version="v2",
        )
        test_domain.init(traverse=False)

    def test_chain_is_built(self, test_domain):
        assert test_domain._upcaster_chain.needs_upcasting("Test.OrderShipped.v1")

    def test_chain_resolves_to_current_class(self, test_domain):
        cls = test_domain._upcaster_chain.resolve_event_class("Test.OrderShipped.v1")
        assert cls is OrderShipped

    def test_upcast_transforms_data(self, test_domain):
        data = {"order_id": "123", "tracking_number": "TRACK-1"}
        result = test_domain._upcaster_chain.upcast("Test.OrderShipped", "v1", data)
        assert result["carrier"] == "unknown"
        assert result["order_id"] == "123"

    def test_current_version_not_in_chain(self, test_domain):
        assert not test_domain._upcaster_chain.needs_upcasting("Test.OrderShipped.v2")


class TestMultiStepChain:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlacedV3, part_of=Order)
        test_domain.upcaster(
            UpcastOrderPlacedV1ToV2,
            event_type=OrderPlacedV3,
            from_version="v1",
            to_version="v2",
        )
        test_domain.upcaster(
            UpcastOrderPlacedV2ToV3,
            event_type=OrderPlacedV3,
            from_version="v2",
            to_version="v3",
        )
        test_domain.init(traverse=False)

    def test_v1_chain_exists(self, test_domain):
        assert test_domain._upcaster_chain.needs_upcasting("Test.OrderPlacedV3.v1")

    def test_v2_chain_exists(self, test_domain):
        assert test_domain._upcaster_chain.needs_upcasting("Test.OrderPlacedV3.v2")

    def test_v1_upcast_applies_both_steps(self, test_domain):
        data = {"order_id": "123", "amount": 99.99}
        result = test_domain._upcaster_chain.upcast("Test.OrderPlacedV3", "v1", data)
        assert result["currency"] == "USD"
        assert result["total_amount"] == 99.99
        assert "amount" not in result

    def test_v2_upcast_applies_one_step(self, test_domain):
        data = {"order_id": "123", "amount": 99.99, "currency": "EUR"}
        result = test_domain._upcaster_chain.upcast("Test.OrderPlacedV3", "v2", data)
        assert result["total_amount"] == 99.99
        assert result["currency"] == "EUR"  # Preserved from v2 data
        assert "amount" not in result

    def test_both_old_versions_resolve_to_current_class(self, test_domain):
        cls_v1 = test_domain._upcaster_chain.resolve_event_class(
            "Test.OrderPlacedV3.v1"
        )
        cls_v2 = test_domain._upcaster_chain.resolve_event_class(
            "Test.OrderPlacedV3.v2"
        )
        assert cls_v1 is OrderPlacedV3
        assert cls_v2 is OrderPlacedV3


class TestNoUpcasting:
    @pytest.fixture(autouse=True)
    def register_elements(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderShipped, part_of=Order)
        test_domain.init(traverse=False)

    def test_no_chain_for_current_version(self, test_domain):
        assert not test_domain._upcaster_chain.needs_upcasting("Test.OrderShipped.v2")

    def test_resolve_returns_none(self, test_domain):
        assert (
            test_domain._upcaster_chain.resolve_event_class("Test.OrderShipped.v2")
            is None
        )

    def test_upcast_returns_data_unchanged(self, test_domain):
        data = {"order_id": "123", "tracking_number": "T1"}
        result = test_domain._upcaster_chain.upcast("Test.OrderShipped", "v2", data)
        assert result == data


# ── Validation / error tests ─────────────────────────────────────────────


class TestDuplicateUpcaster:
    def test_error_on_duplicate_from_version(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderShipped, part_of=Order)

        test_domain.upcaster(
            UpcastOrderShippedV1ToV2,
            event_type=OrderShipped,
            from_version="v1",
            to_version="v2",
        )

        class DuplicateUpcaster(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                return data

        test_domain.upcaster(
            DuplicateUpcaster,
            event_type=OrderShipped,
            from_version="v1",
            to_version="v2",
        )

        with pytest.raises(ConfigurationError, match="Duplicate upcaster"):
            test_domain.init(traverse=False)


class TestCycleDetection:
    def test_error_on_cycle(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderShipped, part_of=Order)

        class CycleA(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                return data

        class CycleB(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                return data

        test_domain.upcaster(
            CycleA, event_type=OrderShipped, from_version="v1", to_version="v2"
        )
        test_domain.upcaster(
            CycleB, event_type=OrderShipped, from_version="v2", to_version="v1"
        )

        with pytest.raises(ConfigurationError, match="does not converge"):
            test_domain.init(traverse=False)


class TestNonConvergentChain:
    def test_error_on_multiple_terminal_versions(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlacedV3, part_of=Order)

        class BranchA(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                return data

        class BranchB(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                return data

        # v1→v2 and v1a→v3 — two terminal versions (v2 and v3)
        test_domain.upcaster(
            BranchA, event_type=OrderPlacedV3, from_version="v1", to_version="v2"
        )
        test_domain.upcaster(
            BranchB, event_type=OrderPlacedV3, from_version="v1a", to_version="v3"
        )

        with pytest.raises(ConfigurationError, match="does not converge"):
            test_domain.init(traverse=False)


class TestChainDoesNotReachCurrentVersion:
    def test_error_when_terminal_version_has_no_event(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderShipped, part_of=Order)  # __version__ = "v2"

        class WrongTarget(BaseUpcaster):
            def upcast(self, data: dict) -> dict:
                return data

        # v1→v99, but no event registered as v99
        test_domain.upcaster(
            WrongTarget, event_type=OrderShipped, from_version="v1", to_version="v99"
        )

        with pytest.raises(
            ConfigurationError, match="no event is registered with type string"
        ):
            test_domain.init(traverse=False)
