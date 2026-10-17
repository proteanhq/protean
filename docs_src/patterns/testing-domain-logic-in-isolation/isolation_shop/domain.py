from datetime import UTC, datetime

from protean import Domain, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import (
    Auto,
    Date,
    DateTime,
    Dict,
    Float,
    HasMany,
    Identifier,
    Integer,
    List,
    String,
)
from protean.utils.globals import current_domain

domain = Domain(name="isolation_shop")

CURRENCIES = {"USD", "EUR", "GBP", "INR"}


@domain.value_object
class Money:
    amount = Float(required=True)
    currency = String(required=True, max_length=3)

    @invariant.post
    def amount_cannot_be_negative(self):
        if self.amount < 0:
            raise ValidationError({"amount": ["Amount cannot be negative"]})

    @invariant.post
    def currency_must_be_known(self):
        if self.currency not in CURRENCIES:
            raise ValidationError({"currency": [f"Invalid currency: {self.currency}"]})

    def add(self, other: "Money") -> "Money":
        if other.currency != self.currency:
            raise ValidationError({"currency": ["Cannot add different currencies"]})
        return Money(amount=self.amount + other.amount, currency=self.currency)


@domain.value_object
class DateRange:
    start_date = Date(required=True)
    end_date = Date(required=True)

    @invariant.post
    def start_must_not_follow_end(self):
        if self.start_date > self.end_date:
            raise ValidationError(
                {"start_date": ["Start date must be on or before end date"]}
            )

    def contains(self, day) -> bool:
        return self.start_date <= day <= self.end_date

    def overlaps(self, other: "DateRange") -> bool:
        return self.start_date <= other.end_date and other.start_date <= self.end_date


@domain.value_object
class Email:
    address = String(required=True, max_length=254)


@domain.aggregate
class Order:
    order_id = Auto(identifier=True)
    customer_id = Identifier(required=True)
    status = String(max_length=20, default="draft")
    placed_at = DateTime()
    total = Float(default=0.0)
    discount = Float(default=0.0)
    tracking_number = String(max_length=50)
    items = HasMany("OrderItem")

    @invariant.post
    def placed_order_must_have_items(self):
        if self.status == "placed" and not self.items:
            raise ValidationError(
                {"items": ["A placed order must have at least one item"]}
            )

    @invariant.post
    def discount_cannot_exceed_total(self):
        if self.discount > self.total:
            raise ValidationError(
                {"discount": ["Discount cannot exceed the order total"]}
            )

    def place(self):
        if self.status != "draft":
            raise ValidationError({"status": ["Only draft orders can be placed"]})

        self.status = "placed"
        self.placed_at = datetime.now(UTC)
        self.raise_(
            OrderPlaced(
                order_id=self.order_id,
                customer_id=self.customer_id,
                items=[
                    {"product_id": item.product_id, "quantity": item.quantity}
                    for item in self.items
                ],
                total=self.total,
            )
        )

    def cancel(self, reason: str):
        if self.status == "cancelled":
            raise ValidationError({"status": ["Order is already cancelled"]})

        was_shipped = self.status == "shipped"
        self.status = "cancelled"
        self.raise_(OrderCancelled(order_id=self.order_id, reason=reason))
        if was_shipped:
            self.raise_(
                ShipmentInterceptRequested(
                    order_id=self.order_id,
                    tracking_number=self.tracking_number,
                )
            )

    def ship(self, tracking_number: str):
        if self.status != "placed":
            raise ValidationError({"status": ["Only placed orders can be shipped"]})

        self.status = "shipped"
        self.tracking_number = tracking_number

    def add_item(self, product_id, product_name, quantity, unit_price):
        self.add_items(
            OrderItem(
                product_id=product_id,
                product_name=product_name,
                quantity=quantity,
                unit_price=unit_price,
            )
        )

    def remove_item(self, product_id):
        self.remove_items(self._item_for(product_id))

    def update_item_quantity(self, product_id, quantity):
        self._item_for(product_id).quantity = quantity

    def _item_for(self, product_id):
        for item in self.items:
            if item.product_id == product_id:
                return item
        raise ValidationError({"items": [f"No item for product {product_id}"]})


@domain.entity(part_of=Order)
class OrderItem:
    product_id = Identifier(required=True)
    product_name = String(max_length=100)
    quantity = Integer(required=True, min_value=1)
    unit_price = Float(required=True, min_value=0.0)


@domain.event(part_of=Order)
class OrderPlaced:
    order_id = Identifier(required=True)
    customer_id = Identifier(required=True)
    items = List(content_type=Dict, default=list)
    total = Float(required=True)


@domain.event(part_of=Order)
class OrderCancelled:
    order_id = Identifier(required=True)
    reason = String(max_length=255)


@domain.event(part_of=Order)
class ShipmentInterceptRequested:
    order_id = Identifier(required=True)
    tracking_number = String(max_length=50)


@domain.aggregate
class Account:
    account_id = Auto(identifier=True)
    balance = Float(default=0.0)
    overdraft_limit = Float(default=0.0, min_value=0.0)
    status = String(max_length=20, default="active")
    risk_score = Integer(default=0)

    @invariant.pre
    def closed_account_cannot_change(self):
        if self.status == "closed":
            raise ValidationError({"status": ["Closed accounts cannot be changed"]})

    @invariant.post
    def balance_must_stay_above_overdraft_limit(self):
        if self.balance < -self.overdraft_limit:
            raise ValidationError(
                {"balance": ["Balance cannot go below overdraft limit"]}
            )

    def withdraw(self, amount: float):
        if amount <= 0:
            raise ValidationError({"amount": ["Withdrawal amount must be positive"]})
        if self.status != "active":
            raise ValidationError(
                {"status": ["Cannot withdraw from a non-active account"]}
            )
        if amount > self.balance + self.overdraft_limit:
            raise ValidationError({"balance": ["Insufficient funds"]})

        self.balance -= amount


@domain.event(part_of=Account)
class TransferDebited:
    account_id = Identifier(required=True)
    transfer_id = Identifier(required=True)
    target_account_id = Identifier(required=True)
    amount = Float(required=True)


@domain.aggregate
class CreditPolicy:
    max_transfer_amount = Float(required=True)
    max_risk_score = Integer(required=True)


@domain.domain_service(part_of=[Account, CreditPolicy])
class TransferService:
    def __init__(self, source, policy):
        super().__init__(source, policy)

        self.source = source
        self.policy = policy

    def validate_and_debit(self, amount, transfer_id, target_account_id):
        source, policy = self.source, self.policy
        if amount > policy.max_transfer_amount:
            raise ValidationError(
                {"amount": [f"Exceeds policy limit of {policy.max_transfer_amount}"]}
            )
        if source.risk_score > policy.max_risk_score:
            raise ValidationError(
                {"source": ["Account risk score exceeds the policy maximum"]}
            )

        source.withdraw(amount)
        source.raise_(
            TransferDebited(
                account_id=source.account_id,
                transfer_id=transfer_id,
                target_account_id=target_account_id,
                amount=amount,
            )
        )


@domain.command(part_of=Order)
class PlaceOrder:
    order_id = Identifier(identifier=True)
    customer_id = Identifier(required=True)
    items = List(content_type=Dict, required=True)
    total = Float(required=True)


@domain.command_handler(part_of=Order)
class OrderCommandHandler:
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            total=command.total,
            items=[OrderItem(**item) for item in command.items],
        )
        order.place()
        current_domain.repository_for(Order).add(order)


@domain.aggregate
class Inventory:
    product_id = Identifier(identifier=True)
    available_quantity = Integer(default=0, min_value=0)


@domain.event_handler(part_of=Inventory, stream_category="isolation_shop::order")
class InventoryEventHandler:
    @handle(OrderPlaced)
    def on_order_placed(self, event: OrderPlaced):
        repo = current_domain.repository_for(Inventory)
        for item in event.items:
            inventory = repo.get(item["product_id"])
            inventory.available_quantity -= item["quantity"]
            repo.add(inventory)
