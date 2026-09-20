"""
Command handler with custom error handling via handle_error classmethod.

This example demonstrates:
- The optional handle_error classmethod for custom error recovery
- How the Protean engine calls handle_error when command processing fails
- Error logging and notification patterns
- The handle_error method signature: cls, exc, message

Note: The handle_error method is called by the Protean Engine during
asynchronous processing. In synchronous mode (domain.process(..., asynchronous=False)),
exceptions propagate directly to the caller. This example shows the handler
structure and how handle_error would be invoked by the engine.

Usage:
    command = TransferFunds(
        transfer_id="TXF-001",
        from_account="ACC-001",
        to_account="ACC-002",
        amount=500.00,
    )
    domain.process(command, asynchronous=False)
"""

import logging

from protean import Domain, handle
from protean.fields import Float, Identifier, String

# Domain setup
domain = Domain()

logger = logging.getLogger(__name__)


@domain.aggregate
class Payment:
    """Payment aggregate for fund transfers."""

    payment_id: Identifier(identifier=True)
    from_account: String(required=True)
    to_account: String(required=True)
    amount: Float(required=True)
    status: String(default="pending")
    error_message: String()

    def execute(self):
        """Execute the payment transfer."""
        if self.amount <= 0:
            raise ValueError("Transfer amount must be positive")
        if self.from_account == self.to_account:
            raise ValueError("Cannot transfer to the same account")
        self.status = "completed"

    def mark_failed(self, reason: str):
        """Mark the payment as failed."""
        self.status = "failed"
        self.error_message = reason


@domain.command(part_of="Payment")
class TransferFunds:
    """Command to transfer funds between accounts."""

    transfer_id: Identifier(required=True)
    from_account: String(required=True)
    to_account: String(required=True)
    amount: Float(required=True)


@domain.command_handler(part_of=Payment)
class PaymentCommandHandler:
    """Handler for payment commands with custom error handling.

    The handle_error classmethod is called by the Protean Engine when
    an exception occurs during asynchronous command processing. It provides
    a hook for logging, notification, or recovery logic.

    Error handling flow:
    1. Handler method raises exception
    2. Engine catches the exception and logs it
    3. Engine calls handle_error(exc, message)
    4. Processing continues with the next command
    """

    @handle(TransferFunds)
    def handle_transfer(self, command: TransferFunds):
        """Handle TransferFunds command."""
        payment = Payment(
            payment_id=command.transfer_id,
            from_account=command.from_account,
            to_account=command.to_account,
            amount=command.amount,
        )
        payment.execute()
        domain.repository_for(Payment).add(payment)
        return payment.payment_id

    @classmethod
    def handle_error(cls, exc: Exception, message) -> None:
        """Custom error handling for failed payment commands.

        Called by the Protean Engine when an exception occurs during
        asynchronous command processing. The default implementation
        in HandlerMixin does nothing; override to add custom behavior.

        Args:
            exc: The exception that was raised during handling
            message: The original command message being processed
        """
        logger.error(
            "Payment command failed: %s (type: %s)",
            str(exc),
            type(exc).__name__,
        )


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Successful transfer
        transfer_cmd = TransferFunds(
            transfer_id="TXF-001",
            from_account="ACC-001",
            to_account="ACC-002",
            amount=500.00,
        )
        domain.process(transfer_cmd, asynchronous=False)
        print("Transfer completed successfully")

        # Transfer that will fail (same account)
        bad_cmd = TransferFunds(
            transfer_id="TXF-002",
            from_account="ACC-001",
            to_account="ACC-001",
            amount=100.00,
        )
        try:
            domain.process(bad_cmd, asynchronous=False)
        except Exception as e:
            print(f"Transfer failed: {e}")
            # In async mode, handle_error would be called by the engine
