"""Tests for Finding #5: Commands without handlers emit a warning.

During _validate_domain(), every registered Command without a corresponding
CommandHandler should produce a warning log so developers are alerted early
instead of discovering the gap at runtime.
"""

import logging


from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Identifier, String
from protean.utils.mixins import handle


class Order(BaseAggregate):
    order_id: Identifier(identifier=True)
    customer: String()


class PlaceOrder(BaseCommand):
    order_id: Identifier()
    customer: String()


class CancelOrder(BaseCommand):
    order_id: Identifier()
    reason: String()


class OrderCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def handle_place_order(self, command: PlaceOrder) -> None:
        pass


class TestCommandWithoutHandlerWarning:
    """Tests that unhandled commands produce warnings at domain init."""

    def test_command_without_handler_logs_warning(self, test_domain, caplog):
        """A command with no registered handler triggers a warning."""
        test_domain.register(Order)
        test_domain.register(CancelOrder, part_of=Order)

        with caplog.at_level(logging.WARNING, logger="protean.domain"):
            test_domain.init(traverse=False)

        assert any(
            "CancelOrder" in record.message and "handler" in record.message
            for record in caplog.records
        )

    def test_command_with_handler_no_warning(self, test_domain, caplog):
        """A command with a registered handler does not trigger a warning."""
        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(OrderCommandHandler, part_of=Order)

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="protean.domain"):
            test_domain.init(traverse=False)

        # Only check records captured during this test's init()
        assert not any(
            "PlaceOrder" in record.message and "handler" in record.message
            for record in caplog.records
        )

    def test_mixed_handled_and_unhandled_commands(self, test_domain, caplog):
        """Only unhandled commands produce warnings; handled ones are silent."""
        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(CancelOrder, part_of=Order)
        test_domain.register(OrderCommandHandler, part_of=Order)

        with caplog.at_level(logging.WARNING, logger="protean.domain"):
            test_domain.init(traverse=False)

        warning_messages = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        # CancelOrder has no handler — should warn
        assert any("CancelOrder" in msg for msg in warning_messages)
        # PlaceOrder has a handler — should NOT warn
        assert not any("PlaceOrder" in msg for msg in warning_messages)

    def test_all_commands_handled_no_warnings(self, test_domain, caplog):
        """When every command has a handler, no warnings are produced."""

        class FullOrderHandler(BaseCommandHandler):
            @handle(PlaceOrder)
            def place(self, command: PlaceOrder) -> None:
                pass

            @handle(CancelOrder)
            def cancel(self, command: CancelOrder) -> None:
                pass

        test_domain.register(Order)
        test_domain.register(PlaceOrder, part_of=Order)
        test_domain.register(CancelOrder, part_of=Order)
        test_domain.register(FullOrderHandler, part_of=Order)

        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="protean.domain"):
            test_domain.init(traverse=False)

        assert not any(
            "does not have a registered handler" in record.message
            for record in caplog.records
        )
