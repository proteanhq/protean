import logging

from protean import Domain, handle
from protean.fields import String

domain = Domain(name="Accounts")

logger = logging.getLogger(__name__)


@domain.aggregate
class Account:
    email: String(required=True)
    name: String(required=True)


@domain.command(part_of=Account)
class RegisterCommand:
    email: String(required=True)
    name: String(required=True)


# --8<-- [start:handler]
@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(RegisterCommand)
    def register(self, command: RegisterCommand):
        # Command handling logic that might raise exceptions
        ...

    @classmethod
    def handle_error(cls, exc: Exception, message):
        """Custom error handling logic for command processing failures"""
        # Log the error
        logger.error(f"Failed to process command: {exc}")

        # Perform recovery operations
        # Example: notify monitoring systems, attempt retry, etc.


# --8<-- [end:handler]
