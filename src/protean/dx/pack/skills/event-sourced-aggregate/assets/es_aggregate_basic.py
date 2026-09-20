"""
Basic event-sourced aggregate with the @apply pattern.

This example demonstrates:
- Enabling event sourcing with `is_event_sourced=True`
- The `@apply` decorator for event replay/reconstruction
- Factory classmethod pattern for aggregate creation
- Business methods that mutate state AND raise events
- State reconstruction via `from_events()`
- Version tracking across events

Domain: User registration lifecycle
    - Users are registered (initial creation event)
    - Users can be activated or deactivated
    - All state changes are captured as events

Usage:
    from es_aggregate_basic import User, domain

    domain.init(traverse=False)
    with domain.domain_context():
        user = User.register(user_id="U-001", name="Alice", email="alice@example.com")
        user.activate()
"""

from protean import Domain
from protean.core.aggregate import apply
from protean.fields import Identifier, String

# Domain setup
domain = Domain()


# --- Events ---


@domain.event(part_of="User")
class UserRegistered:
    """Raised when a new user is registered in the system."""

    user_id: Identifier(required=True)
    name: String(required=True, max_length=100)
    email: String(required=True, max_length=255)


@domain.event(part_of="User")
class UserActivated:
    """Raised when a user account is activated."""

    user_id: Identifier(required=True)


@domain.event(part_of="User")
class UserDeactivated:
    """Raised when a user account is deactivated."""

    user_id: Identifier(required=True)
    reason: String(max_length=500)


@domain.event(part_of="User")
class UserNameChanged:
    """Raised when a user changes their name."""

    user_id: Identifier(required=True)
    name: String(required=True, max_length=100)


# --- Aggregate ---


@domain.aggregate(is_event_sourced=True)
class User:
    """Event-sourced user aggregate.

    Business methods validate and raise events via raise_().
    @apply methods handle all state mutations (called automatically by raise_()).
    """

    user_id: Identifier(identifier=True)
    name: String(required=True, max_length=100)
    email: String(required=True, max_length=255)
    status: String(
        max_length=20,
        choices=["INACTIVE", "ACTIVE", "DEACTIVATED"],
        default="INACTIVE",
    )

    # --- Factory classmethod ---

    @classmethod
    def register(cls, user_id, name, email):
        """Create a new user and raise the registration event.

        Factory classmethods ensure the creation event is always
        the first event in the aggregate's stream.
        """
        user = cls(user_id=user_id, name=name, email=email)
        user.raise_(UserRegistered(user_id=user_id, name=name, email=email))
        return user

    # --- Business methods (validate then raise; @apply handles state) ---

    def activate(self):
        """Activate the user account."""
        if self.status == "ACTIVE":
            raise ValueError("User is already active")
        self.raise_(UserActivated(user_id=self.user_id))

    def deactivate(self, reason=""):
        """Deactivate the user account."""
        if self.status == "DEACTIVATED":
            raise ValueError("User is already deactivated")
        self.raise_(UserDeactivated(user_id=self.user_id, reason=reason))

    def change_name(self, new_name):
        """Change the user's name."""
        if not new_name or not new_name.strip():
            raise ValueError("Name cannot be empty")
        self.raise_(UserNameChanged(user_id=self.user_id, name=new_name))

    # --- @apply methods (for replaying events during state reconstruction) ---

    @apply
    def registered(self, event: UserRegistered):
        self.user_id = event.user_id
        self.name = event.name
        self.email = event.email
        self.status = "INACTIVE"

    @apply
    def activated(self, event: UserActivated):
        self.status = "ACTIVE"

    @apply
    def deactivated(self, event: UserDeactivated):
        self.status = "DEACTIVATED"

    @apply
    def name_changed(self, event: UserNameChanged):
        self.name = event.name


# Example usage
if __name__ == "__main__":  # pragma: no cover
    domain.init(traverse=False)

    with domain.domain_context():
        # Create a new user via factory classmethod
        user = User.register(
            user_id="U-001", name="Alice Smith", email="alice@example.com"
        )
        print(f"Created: {user.name}, status={user.status}")
        print(f"Events so far: {len(user._events)}")

        # Activate the user
        user.activate()
        print(f"After activate: status={user.status}")

        # Change name
        user.change_name("Alice Johnson")
        print(f"After name change: name={user.name}")

        # Reconstruct from events
        reconstructed = User.from_events(user._events)
        print(
            f"\nReconstructed: name={reconstructed.name}, status={reconstructed.status}"
        )
        print(f"Versions match: {user._version == reconstructed._version}")
