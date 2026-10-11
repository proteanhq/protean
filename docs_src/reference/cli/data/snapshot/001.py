# --8<-- [start:domain]
from protean import Domain, apply
from protean.fields import Identifier, String

domain = Domain(name="Identity")


@domain.event(part_of="User")
class Registered:
    user_id: Identifier(required=True)
    email: String(required=True)


@domain.aggregate(event_sourced=True)
class User:
    user_id: Identifier(identifier=True)
    email: String(required=True)

    @classmethod
    def register(cls, user_id: str, email: str) -> "User":
        user = cls(user_id=user_id, email=email)
        user.raise_(Registered(user_id=user_id, email=email))
        return user

    @apply
    def registered(self, event: Registered) -> None:
        self.user_id = event.user_id
        self.email = event.email


@domain.event(part_of="Order")
class OrderPlaced:
    order_id: Identifier(required=True)
    user_id: Identifier(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    order_id: Identifier(identifier=True)
    user_id: Identifier(required=True)

    @classmethod
    def place(cls, order_id: str, user_id: str) -> "Order":
        order = cls(order_id=order_id, user_id=user_id)
        order.raise_(OrderPlaced(order_id=order_id, user_id=user_id))
        return order

    @apply
    def placed(self, event: OrderPlaced) -> None:
        self.order_id = event.order_id
        self.user_id = event.user_id


domain.init(traverse=False)

with domain.domain_context():
    domain.repository_for(User).add(User.register("abc-123", "ann@example.com"))
    domain.repository_for(User).add(User.register("def-456", "bob@example.com"))
    domain.repository_for(Order).add(Order.place("ord-1", user_id="abc-123"))
# --8<-- [end:domain]

# --8<-- [start:api]
with domain.domain_context():
    # Single aggregate instance
    domain.create_snapshot(User, "abc-123")

    # All instances of one aggregate
    count = domain.create_snapshots(User)

    # All event-sourced aggregates
    results = domain.create_all_snapshots()  # {"User": 2, "Order": 1}
# --8<-- [end:api]
