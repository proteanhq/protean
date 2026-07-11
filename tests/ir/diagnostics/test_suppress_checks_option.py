"""Diagnostics: TestSuppressChecksOption."""

from protean import Domain
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _codes_for,
)


class TestSuppressChecksOption:
    """The per-element ``suppress_checks`` option drops the named codes."""

    def test_aggregate_suppresses_its_own_code(self):
        domain = Domain(name="SuppressAgg", root_path=".")

        @domain.aggregate(suppress_checks=["AGGREGATE_WITHOUT_COMMAND_HANDLER"])
        class Suppressed:
            name = String(max_length=50)

        @domain.aggregate
        class Kept:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        # Suppressed aggregate: its finding is gone; Kept still has it. This
        # also proves one element's suppression does not affect another.
        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" not in _codes_for(ir, "Suppressed")
        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" in _codes_for(ir, "Kept")

    def test_event_suppression_via_registry_no_options_block(self):
        """Events carry no IR ``options`` block, so suppression must resolve
        from the registry — this is the load-bearing no-options-block path."""
        domain = Domain(name="SuppressEvent", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.event(part_of=Order, suppress_checks=["UNHANDLED_EVENT"])
        class OrderPlaced:
            name = String()

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert "UNHANDLED_EVENT" not in _codes_for(ir, "OrderPlaced")

    def test_command_inherits_suppress_checks(self):
        """Commands pick up ``suppress_checks`` via the inherited option set
        (``BaseMessageType`` → filtered comprehension in command.py)."""
        domain = Domain(name="SuppressCommand", root_path=".")

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        @domain.command(part_of=Order, suppress_checks=["UNUSED_COMMAND"])
        class PlaceOrder:
            name = String(required=True)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert "UNUSED_COMMAND" not in _codes_for(ir, "PlaceOrder")

    def test_unmatched_code_removes_nothing(self):
        domain = Domain(name="SuppressNoMatch", root_path=".")

        @domain.aggregate(suppress_checks=["NONEXISTENT_CODE"])
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" in _codes_for(ir, "Order")

    def test_bare_string_is_normalised_to_single_code(self):
        """A bare string (not a list) is treated as one code, not iterated
        character-by-character — otherwise the finding silently survives."""
        domain = Domain(name="SuppressBareString", root_path=".")

        @domain.aggregate(suppress_checks="AGGREGATE_WITHOUT_COMMAND_HANDLER")
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert "AGGREGATE_WITHOUT_COMMAND_HANDLER" not in _codes_for(ir, "Order")
