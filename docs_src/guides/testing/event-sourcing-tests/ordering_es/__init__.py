# --8<-- [start:domain]
from protean import Domain, apply, handle
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String, ValueObject
from protean.utils.globals import current_domain

domain = Domain(name="Ordering")


@domain.value_object
class Pricing:
    grand_total: Float(required=True)


@domain.event(part_of="Order")
class OrderCreated:
    order_id: Identifier(required=True)
    customer: String(required=True)
    amount: Float(required=True)


@domain.event(part_of="Order")
class OrderConfirmed:
    order_id: Identifier(required=True)


@domain.event(part_of="Order")
class PaymentPending:
    order_id: Identifier(required=True)
    payment_id: String(required=True)


@domain.event(part_of="Order")
class PaymentFailed:
    order_id: Identifier(required=True)
    payment_id: String(required=True)


@domain.aggregate(event_sourced=True)
class Order:
    order_id: Identifier(identifier=True)
    customer: String(max_length=100)
    pricing = ValueObject(Pricing)
    status: String(max_length=20)

    @classmethod
    def create(cls, order_id, customer, amount):
        order = cls._create_new(order_id=order_id)
        order.raise_(OrderCreated(order_id=order_id, customer=customer, amount=amount))
        return order

    def confirm(self):
        self.raise_(OrderConfirmed(order_id=self.order_id))

    def initiate_payment(self, payment_id):
        if self.status != "CONFIRMED":
            raise ValidationError(
                {"status": ["Order must be confirmed before payment"]}
            )
        self.raise_(PaymentPending(order_id=self.order_id, payment_id=payment_id))

    @apply
    def on_created(self, event: OrderCreated):
        self.order_id = event.order_id
        self.customer = event.customer
        self.pricing = Pricing(grand_total=event.amount)
        self.status = "CREATED"

    @apply
    def on_confirmed(self, event: OrderConfirmed):
        self.status = "CONFIRMED"

    @apply
    def on_payment_pending(self, event: PaymentPending):
        self.status = "PAYMENT_PENDING"

    @apply
    def on_payment_failed(self, event: PaymentFailed):
        self.status = "CONFIRMED"


@domain.command(part_of=Order)
class CreateOrder:
    order_id: Identifier(identifier=True)
    customer: String(required=True)
    amount: Float(required=True)


@domain.command(part_of=Order)
class ConfirmOrder:
    order_id: Identifier(identifier=True)


@domain.command(part_of=Order)
class InitiatePayment:
    order_id: Identifier(identifier=True)
    payment_id: String(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(CreateOrder)
    def create_order(self, command: CreateOrder):
        order = Order.create(command.order_id, command.customer, command.amount)
        current_domain.repository_for(Order).add(order)
        return order.order_id  # the DSL finds the new aggregate by this id

    @handle(ConfirmOrder)
    def confirm_order(self, command: ConfirmOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.confirm()
        repo.add(order)

    @handle(InitiatePayment)
    def initiate_payment(self, command: InitiatePayment):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)
        order.initiate_payment(command.payment_id)
        repo.add(order)


# --8<-- [end:domain]
