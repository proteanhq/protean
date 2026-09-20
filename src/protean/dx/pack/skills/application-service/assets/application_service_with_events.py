"""
Application service where the aggregate raises domain events during mutation.

This example demonstrates:
- Aggregate raising domain events via self.raise_() during state changes
- Events committed alongside aggregate state within the @use_case UnitOfWork
- Multiple events raised across different use case invocations
- Factory classmethod on aggregate for encapsulating creation logic

Usage:
    svc = UserApplicationServices()
    user_id = svc.register_user(email="john@example.com", name="John Doe")
    svc.activate_user(user_id=user_id)
"""

from protean import Domain, current_domain, use_case
from protean.fields import Identifier, String

# Domain setup
domain = Domain()


@domain.event(part_of="User")
class UserRegistered:
    """Event raised when a new user registers."""

    user_id: Identifier(required=True)
    email: String(required=True)
    name: String(required=True)


@domain.event(part_of="User")
class UserActivated:
    """Event raised when a user account is activated."""

    user_id: Identifier(required=True)


@domain.aggregate
class User:
    """User aggregate that raises events on state changes."""

    email: String(required=True)
    name: String(required=True)
    status: String(choices=["INACTIVE", "ACTIVE", "ARCHIVED"], default="INACTIVE")

    @classmethod
    def register(cls, email: str, name: str):
        """Factory method for user registration.

        Creates a new user and raises a UserRegistered event.
        Business logic (event raising) stays in the aggregate.
        """
        user = cls(email=email, name=name)
        user.raise_(
            UserRegistered(
                user_id=user.id,
                email=user.email,
                name=user.name,
            )
        )
        return user

    def activate(self):
        """Activate the user account.

        Changes status and raises a UserActivated event.
        """
        self.status = "ACTIVE"
        self.raise_(UserActivated(user_id=self.id))


@domain.application_service(part_of=User)
class UserApplicationServices:
    """Application service that orchestrates User operations.

    The aggregate raises events during mutation. These events are
    committed alongside the aggregate state within the UnitOfWork
    managed by @use_case.
    """

    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        """Register a new user.

        Uses the aggregate factory method which raises UserRegistered event.
        """
        user = User.register(email=email, name=name)
        current_domain.repository_for(User).add(user)
        return user.id

    @use_case
    def activate_user(self, user_id: Identifier) -> None:
        """Activate an existing user.

        Loads the user, activates them (raising UserActivated event),
        and persists the aggregate with its events.
        """
        user = current_domain.repository_for(User).get(user_id)
        user.activate()
        current_domain.repository_for(User).add(user)


# Example usage
if __name__ == "__main__":
    domain.init(traverse=False)

    with domain.domain_context():
        svc = UserApplicationServices()

        # Register — raises UserRegistered event
        user_id = svc.register_user(email="john@example.com", name="John Doe")
        print(f"Registered user: {user_id}")

        # Activate — raises UserActivated event
        svc.activate_user(user_id=user_id)
        user = current_domain.repository_for(User).get(user_id)
        print(f"User status: {user.status}")
