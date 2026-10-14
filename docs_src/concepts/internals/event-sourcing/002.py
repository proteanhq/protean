# --8<-- [start:domain]
from protean import Domain, apply
from protean.fields import Identifier, String

domain = Domain(name="Accounts")


@domain.event(part_of="User")
class Registered:
    user_id: Identifier(required=True)
    email: String(required=True)


@domain.event(part_of="User")
class EmailChanged:
    user_id: Identifier(required=True)
    email: String(required=True)


@domain.aggregate(event_sourced=True)
class User:
    user_id: Identifier(identifier=True)
    email: String(required=True)

    @classmethod
    def register(cls, user_id, email):
        user = cls._create_new(user_id=user_id)
        user.raise_(Registered(user_id=user_id, email=email))
        return user

    def change_email(self, email):
        self.raise_(EmailChanged(user_id=self.user_id, email=email))

    @apply
    def registered(self, event: Registered):
        self.user_id = event.user_id
        self.email = event.email

    @apply
    def email_changed(self, event: EmailChanged):
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
    def place(cls, order_id, user_id):
        order = cls._create_new(order_id=order_id)
        order.raise_(OrderPlaced(order_id=order_id, user_id=user_id))
        return order

    @apply
    def placed(self, event: OrderPlaced):
        self.order_id = event.order_id
        self.user_id = event.user_id


domain.init(traverse=False)

with domain.domain_context():
    user = User.register("user-id-123", "ann@example.com")
    user.change_email("ann@work.example.com")
    domain.repository_for(User).add(user)
    domain.repository_for(User).add(User.register("user-id-456", "bob@example.com"))
    domain.repository_for(Order).add(Order.place("ord-1", user_id="user-id-123"))
# --8<-- [end:domain]

# --8<-- [start:api]
with domain.domain_context():
    # Single aggregate instance
    domain.create_snapshot(User, "user-id-123")

    # All instances of one aggregate
    count = domain.create_snapshots(User)

    # All event-sourced aggregates in the domain
    results = domain.create_all_snapshots()  # {"User": 2, "Order": 1}
# --8<-- [end:api]
