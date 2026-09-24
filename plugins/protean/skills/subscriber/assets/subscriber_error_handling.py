"""
Subscriber with custom handle_error classmethod for error recovery.

This example demonstrates:
- Overriding the handle_error classmethod for custom error handling
- How the Protean Engine calls handle_error when subscriber processing fails
- Error logging and recovery patterns
- The handle_error method signature: cls, exc, message

Note: The handle_error method is called by the Protean Engine during
asynchronous processing. In synchronous mode, exceptions propagate
directly to the caller. This example shows the handler structure
and how handle_error would be invoked by the engine.

Usage:
    domain.brokers["default"].publish(
        "inventory_updates",
        {"product_id": "PROD-001", "quantity_change": -5},
    )
"""

import logging

from protean import Domain
from protean.fields import Integer, String

# Domain setup
domain = Domain()
domain.config["message_processing"] = "sync"

logger = logging.getLogger(__name__)


@domain.aggregate
class Inventory:
    """Inventory aggregate tracking product stock levels."""

    product_id: String(identifier=True, required=True)
    product_name: String(required=True)
    quantity: Integer(default=0)

    def adjust_quantity(self, change: int):
        """Adjust stock quantity by the given amount.

        Args:
            change: Positive to add stock, negative to remove.

        Raises:
            ValueError: If adjustment would result in negative stock.
        """
        new_quantity = self.quantity + change
        if new_quantity < 0:
            raise ValueError(
                f"Cannot reduce stock below zero. Current: {self.quantity}, change: {change}"
            )
        self.quantity = new_quantity


@domain.subscriber(stream="inventory_updates")
class InventoryUpdateSubscriber:
    """Processes inventory adjustment messages from an external warehouse system.

    Listens to the 'inventory_updates' broker stream. When a stock adjustment
    message arrives, it loads the Inventory aggregate and adjusts the quantity.

    Includes custom handle_error to log failed adjustments without crashing
    the message processing pipeline.
    """

    def __call__(self, payload: dict) -> None:
        """Process inventory update from warehouse system.

        Args:
            payload: Raw dict from broker, e.g.
                {"product_id": "PROD-001", "quantity_change": -5}
        """
        product_id = payload["product_id"]
        quantity_change = payload["quantity_change"]

        repo = domain.repository_for(Inventory)
        inventory = repo.get(product_id)
        inventory.adjust_quantity(quantity_change)
        repo.add(inventory)

        logger.info(
            "Inventory for %s adjusted by %d (new qty: %d)",
            product_id,
            quantity_change,
            inventory.quantity,
        )

    @classmethod
    def handle_error(cls, exc: Exception, message: dict) -> None:
        """Custom error handling for failed inventory updates.

        Called by the Protean Engine when an exception occurs during
        asynchronous message processing. Logs the error with context
        about the failed message for debugging and monitoring.

        Args:
            exc: The exception that was raised during handling
            message: The original message being processed
        """
        product_id = message.get("product_id", "unknown") if message else "unknown"
        logger.error(
            "Inventory update failed for product %s: %s (type: %s)",
            product_id,
            str(exc),
            type(exc).__name__,
        )


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Create inventory
        inventory = Inventory(
            product_id="PROD-001", product_name="Widget", quantity=100
        )
        domain.repository_for(Inventory).add(inventory)

        # Simulate stock adjustment from warehouse
        domain.brokers["default"].publish(
            "inventory_updates",
            {"product_id": "PROD-001", "quantity_change": -10},
        )

        updated = domain.repository_for(Inventory).get("PROD-001")
        print(f"After adjustment: quantity={updated.quantity}")
        assert updated.quantity == 90

        # Simulate a failing adjustment (would go negative)
        try:
            domain.brokers["default"].publish(
                "inventory_updates",
                {"product_id": "PROD-001", "quantity_change": -200},
            )
        except ValueError as e:
            print(f"Expected error: {e}")
            # In async mode, handle_error would be called by the engine
