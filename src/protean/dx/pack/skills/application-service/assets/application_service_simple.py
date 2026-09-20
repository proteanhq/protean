"""
Simple application service with a single @use_case method.

This example demonstrates:
- Basic application service definition with @domain.application_service decorator
- Required part_of parameter associating the service with an aggregate
- Single @use_case method for registering a user
- Direct invocation pattern (instantiate and call, not domain.process())
- Automatic UnitOfWork wrapping via @use_case
- Synchronous return value (user ID)

Usage:
    svc = UserApplicationServices()
    user_id = svc.register_user(email="john@example.com", name="John Doe")
"""

from protean import Domain, current_domain, use_case
from protean.fields import Identifier, String

# Domain setup
domain = Domain()


@domain.aggregate
class User:
    """User aggregate with basic registration."""

    email: String(required=True)
    name: String(required=True)
    status: String(choices=["INACTIVE", "ACTIVE", "ARCHIVED"], default="INACTIVE")


@domain.application_service(part_of=User)
class UserApplicationServices:
    """Application service for User aggregate.

    This service provides a single use case: registering a new user.
    It demonstrates the fundamental application service pattern:
    1. Accept plain Python arguments
    2. Create the aggregate
    3. Persist via repository
    4. Return the new entity ID
    """

    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        """Register a new user and return their ID.

        Creates a new User aggregate with INACTIVE status and persists it.
        The @use_case decorator ensures this runs within a UnitOfWork.
        """
        user = User(email=email, name=name)
        current_domain.repository_for(User).add(user)
        return user.id


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        svc = UserApplicationServices()

        # Register a new user
        user_id = svc.register_user(email="john@example.com", name="John Doe")
        print(f"Registered user with ID: {user_id}")

        # Verify the user was persisted
        user = current_domain.repository_for(User).get(user_id)
        print(f"User: {user.name} ({user.email}), Status: {user.status}")
