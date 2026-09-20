"""
Subscriber as anti-corruption layer translating external payloads into domain commands.

This example demonstrates:
- The canonical DDD anti-corruption layer pattern
- Translating external system schemas into domain language
- Dispatching internal domain commands from a subscriber
- Shielding the domain from external data format changes
- The subscriber is the ONLY place that knows the external schema

Usage:
    domain.brokers["default"].publish(
        "erp_user_events",
        {
            "event_type": "user.created",
            "data": {
                "userId": "USR-001",
                "firstName": "Alice",
                "lastName": "Johnson",
                "emailAddress": "alice@example.com",
            },
        },
    )
    # ERPUserSubscriber translates the external format and dispatches RegisterCustomer
"""

import logging

from protean import Domain, handle
from protean.fields import Identifier, String

# Domain setup
domain = Domain()
domain.config["message_processing"] = "sync"
domain.config["command_processing"] = "sync"

logger = logging.getLogger(__name__)


@domain.aggregate
class Customer:
    """Customer aggregate in our domain."""

    name: String(required=True)
    email: String(required=True)
    source: String(default="direct")


@domain.command(part_of="Customer")
class RegisterCustomer:
    """Command to register a new customer in our domain.

    This is our domain's own language - no external system terminology.
    """

    customer_id: Identifier(required=True)
    name: String(required=True)
    email: String(required=True)
    source: String(default="erp")


@domain.command_handler(part_of=Customer)
class CustomerCommandHandler:
    """Handles customer-related commands."""

    @handle(RegisterCustomer)
    def register_customer(self, command: RegisterCustomer):
        """Create a new Customer aggregate from the registration command."""
        customer = Customer(
            id=command.customer_id,
            name=command.name,
            email=command.email,
            source=command.source,
        )
        domain.repository_for(Customer).add(customer)


@domain.subscriber(stream="erp_user_events")
class ERPUserSubscriber:
    """Anti-corruption layer for external ERP user events.

    This subscriber is the ONLY place in the domain that understands
    the external ERP system's data format. It translates external
    camelCase fields and nested structures into our domain's own
    command language (RegisterCustomer).

    External ERP format:
        {
            "event_type": "user.created",
            "data": {
                "userId": "USR-001",
                "firstName": "Alice",
                "lastName": "Johnson",
                "emailAddress": "alice@example.com"
            }
        }

    Internal domain command:
        RegisterCustomer(
            customer_id="USR-001",
            name="Alice Johnson",
            email="alice@example.com",
            source="erp"
        )
    """

    def __call__(self, payload: dict) -> None:
        """Translate external ERP event into domain command.

        Args:
            payload: Raw dict from ERP broker stream with camelCase fields.
        """
        event_type = payload.get("event_type", "")

        if event_type == "user.created":
            self._handle_user_created(payload["data"])
        else:
            logger.warning("Unknown ERP event type: %s", event_type)

    def _handle_user_created(self, data: dict) -> None:
        """Translate ERP user.created into RegisterCustomer command.

        This is where the anti-corruption translation happens:
        - camelCase -> snake_case
        - firstName + lastName -> name
        - emailAddress -> email
        - External userId -> customer_id
        """
        command = RegisterCustomer(
            customer_id=data["userId"],
            name=f"{data['firstName']} {data['lastName']}",
            email=data["emailAddress"],
            source="erp",
        )
        domain.process(command)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        # Simulate ERP system publishing a user.created event
        domain.brokers["default"].publish(
            "erp_user_events",
            {
                "event_type": "user.created",
                "data": {
                    "userId": "USR-001",
                    "firstName": "Alice",
                    "lastName": "Johnson",
                    "emailAddress": "alice@example.com",
                },
            },
        )

        # Verify customer was created in our domain
        customer = domain.repository_for(Customer).get("USR-001")
        print(f"Customer: {customer.name} ({customer.email}), source={customer.source}")
        assert customer.name == "Alice Johnson"
        assert customer.email == "alice@example.com"
        assert customer.source == "erp"
        print("Anti-corruption layer working correctly!")
