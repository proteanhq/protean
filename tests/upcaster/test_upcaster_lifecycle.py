"""Tests for #1109: upcasters register through the standard element lifecycle.

Covers registry / ``element_type`` integration, IR elements-index appearance,
and ``domain.check()`` reporting a malformed chain as a structured error
instead of crashing.
"""

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.upcaster import BaseUpcaster
from protean.fields import String
from protean.utils import DomainObjects


class Order(BaseAggregate):
    name = String(max_length=100)


class OrderPlaced(BaseEvent):
    __version__ = 2
    name = String()


class UpcastOrderPlacedV1ToV2(BaseUpcaster):
    def upcast(self, data):
        return data


def _register_valid(test_domain):
    test_domain.register(Order, is_event_sourced=True)
    test_domain.register(OrderPlaced, part_of=Order)
    test_domain.upcaster(
        UpcastOrderPlacedV1ToV2,
        event_type=OrderPlaced,
        from_version=1,
        to_version=2,
    )


class TestUpcasterStandardLifecycle:
    def test_upcaster_carries_the_upcaster_element_type(self):
        assert UpcastOrderPlacedV1ToV2.element_type == DomainObjects.UPCASTER

    def test_registered_upcaster_lands_in_the_domain_registry(self, test_domain):
        _register_valid(test_domain)
        bucket = test_domain._domain_registry._elements[DomainObjects.UPCASTER.value]
        assert UpcastOrderPlacedV1ToV2 in [record.cls for record in bucket.values()]

    def test_upcasters_property_is_sourced_from_the_registry(self, test_domain):
        _register_valid(test_domain)
        assert UpcastOrderPlacedV1ToV2 in test_domain._upcasters

    def test_imperative_register_routes_like_the_decorator(self, test_domain):
        """`domain.register(UpcasterClass, ...)` now works because the class
        carries `element_type`; before #1109 it was rejected as "not a valid
        element". It lands the same registry entry as `@domain.upcaster`."""
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlaced, part_of=Order)
        test_domain.register(
            UpcastOrderPlacedV1ToV2,
            event_type=OrderPlaced,
            from_version=1,
            to_version=2,
        )
        assert UpcastOrderPlacedV1ToV2 in test_domain._upcasters


class TestUpcasterInIR:
    def test_upcaster_appears_in_the_ir_elements_index(self, test_domain):
        _register_valid(test_domain)
        test_domain.init(traverse=False)

        upcasters = test_domain.to_ir()["elements"].get("UPCASTER", [])
        assert len(upcasters) == 1
        assert any("UpcastOrderPlacedV1ToV2" in fqn for fqn in upcasters)


class TestMalformedChainReportedByCheck:
    """A malformed chain is a structured error in check(), not a crash."""

    def test_duplicate_chain_is_a_structured_error(self, test_domain):
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlaced, part_of=Order)

        class UpcastA(BaseUpcaster):
            def upcast(self, data):
                return data

        class UpcastB(BaseUpcaster):
            def upcast(self, data):
                return data

        # Two upcasters for the same event + from_version -> malformed chain.
        test_domain.upcaster(
            UpcastA, event_type=OrderPlaced, from_version=1, to_version=2
        )
        test_domain.upcaster(
            UpcastB, event_type=OrderPlaced, from_version=1, to_version=2
        )

        result = test_domain.check(traverse=False)

        assert result["status"] == "fail"
        assert result["counts"]["errors"] >= 1
        upcaster_errors = [
            e for e in result["errors"] if "upcaster" in e["message"].lower()
        ]
        assert len(upcaster_errors) == 1
        assert upcaster_errors[0]["level"] == "error"

    def test_valid_chain_reports_no_upcaster_error(self, test_domain):
        _register_valid(test_domain)

        result = test_domain.check(traverse=False)

        upcaster_errors = [
            e for e in result["errors"] if "upcaster" in e["message"].lower()
        ]
        assert upcaster_errors == []

    def test_repeated_check_is_idempotent(self, test_domain):
        """A second check() on a malformed domain reports the same single error,
        not a doubled/misleading one — the chain build must not accumulate
        state across calls."""
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlaced, part_of=Order)

        class UpcastA(BaseUpcaster):
            def upcast(self, data):
                return data

        class UpcastB(BaseUpcaster):
            def upcast(self, data):
                return data

        test_domain.upcaster(
            UpcastA, event_type=OrderPlaced, from_version=1, to_version=2
        )
        test_domain.upcaster(
            UpcastB, event_type=OrderPlaced, from_version=1, to_version=2
        )

        first = [
            e
            for e in test_domain.check(traverse=False)["errors"]
            if "upcaster" in e["message"].lower()
        ]
        second = [
            e
            for e in test_domain.check(traverse=False)["errors"]
            if "upcaster" in e["message"].lower()
        ]
        assert len(first) == 1
        assert second == first

    def test_string_event_type_is_a_structured_error_not_a_crash(self, test_domain):
        """A string event_type is tolerated at registration but not resolved;
        check() reports it as a structured error instead of crashing with
        `AttributeError: 'str' object has no attribute '__name__'`."""
        test_domain.register(Order, is_event_sourced=True)
        test_domain.register(OrderPlaced, part_of=Order)

        class UpcastByName(BaseUpcaster):
            def upcast(self, data):
                return data

        test_domain.upcaster(
            UpcastByName, event_type="OrderPlaced", from_version=1, to_version=2
        )

        result = test_domain.check(traverse=False)

        assert result["status"] == "fail"
        by_string = [e for e in result["errors"] if "by string" in e["message"]]
        assert len(by_string) == 1
        assert by_string[0]["level"] == "error"

    def test_check_does_not_build_the_runtime_chain(self, test_domain):
        """check() validates a throwaway chain; the runtime upcaster chain used
        during deserialization stays untouched (the validator is read-only).
        init(), by contrast, builds it."""
        _register_valid(test_domain)

        test_domain.check(traverse=False)
        assert not test_domain._upcaster_chain.needs_upcasting("Test.OrderPlaced.v1")

        test_domain.init(traverse=False)
        assert test_domain._upcaster_chain.needs_upcasting("Test.OrderPlaced.v1")
