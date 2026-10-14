# --8<-- [start:value_objects]
from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Date, Float, String

domain = Domain(name="ValidationLayering")


@domain.value_object
class Email:
    address: String(required=True, max_length=254)

    @invariant.post
    def must_have_valid_format(self):
        if not self.address or "@" not in self.address:
            raise ValidationError({"address": ["Must be a valid email address"]})
        local, _, domain_part = self.address.partition("@")
        if not local or not domain_part or "." not in domain_part:
            raise ValidationError({"address": ["Must be a valid email address"]})


@domain.value_object
class Money:
    amount: Float(required=True)
    currency: String(max_length=3, required=True)

    @invariant.post
    def amount_must_be_non_negative(self):
        if self.amount < 0:
            raise ValidationError({"amount": ["Amount cannot be negative"]})

    @invariant.post
    def currency_must_be_valid(self):
        if self.currency not in {"USD", "EUR", "GBP", "JPY", "CAD"}:
            raise ValidationError({"currency": [f"Invalid currency: {self.currency}"]})


@domain.value_object
class DateRange:
    start_date: Date(required=True)
    end_date: Date(required=True)

    @invariant.post
    def end_must_be_after_start(self):
        if self.end_date <= self.start_date:
            raise ValidationError({"end_date": ["End date must be after start date"]})


# --8<-- [end:value_objects]

# --8<-- [start:aggregate]
from datetime import UTC, datetime

from protean.fields import (
    Auto,
    DateTime,
    HasMany,
    Identifier,
    Integer,
    ValueObject,
)


@domain.entity(part_of="Order")
class OrderItem:
    product_id: Identifier(required=True)
    quantity: Integer(required=True, min_value=1)
    unit_price: Float(required=True, min_value=0.0)


@domain.aggregate
class Order:
    order_id: Auto(identifier=True)
    customer_id: Identifier(required=True)
    items = HasMany(OrderItem)
    status: String(default="draft")
    total = ValueObject(Money)
    discount = ValueObject(Money)
    placed_at: DateTime()
    cancellation_reason: String()

    @invariant.post
    def must_have_items_when_placed(self):
        """An order cannot be placed without items."""
        if self.status != "draft" and not self.items:
            raise ValidationError({"items": ["Order must have at least one item"]})

    @invariant.post
    def discount_cannot_exceed_total(self):
        """Discount cannot be larger than the order total."""
        if self.discount and self.total and self.discount.amount > self.total.amount:
            raise ValidationError({"discount": ["Discount cannot exceed order total"]})

    @invariant.post
    def total_must_match_items(self):
        """Order total must match sum of item totals."""
        if self.items and self.total:
            expected = sum(item.unit_price * item.quantity for item in self.items)
            if abs(self.total.amount - expected) > 0.01:
                raise ValidationError(
                    {
                        "total": [
                            (
                                f"Total {self.total.amount} does not match "
                                f"items total {expected}"
                            )
                        ]
                    }
                )

    def place(self):
        """State machine rule: only a draft order can be placed."""
        if self.status != "draft":
            raise ValidationError({"status": ["Only draft orders can be placed"]})
        self.status = "placed"
        self.placed_at = datetime.now(UTC)

    def cancel(self, reason):
        """State machine rule: only a draft or placed order can be cancelled."""
        if self.status not in ("draft", "placed"):
            raise ValidationError(
                {"status": [f"Cannot cancel an order in '{self.status}' status"]}
            )
        self.status = "cancelled"
        self.cancellation_reason = reason


# --8<-- [end:aggregate]

# --8<-- [start:guards]
from datetime import timedelta

from protean import current_domain, handle
from protean.core.command_handler import BaseCommandHandler
from protean.fields import Boolean


@domain.command(part_of=Order)
class CancelOrder:
    order_id: Identifier(required=True)
    cancelled_by: Identifier(required=True)
    cancelled_by_role: String(required=True)
    reason: String()


@domain.command_handler(part_of=Order)
class OrderCommandHandler(BaseCommandHandler):
    @handle(CancelOrder)
    def cancel_order(self, command: CancelOrder):
        repo = current_domain.repository_for(Order)
        order = repo.get(command.order_id)

        # Layer 4: Authorization check
        if (
            command.cancelled_by_role != "admin"
            and command.cancelled_by != order.customer_id
        ):
            raise ValidationError(
                {"authorization": ["Only the customer or an admin can cancel"]}
            )

        # Layer 4: Time-based business rule
        if order.placed_at and (
            datetime.now(UTC) - order.placed_at > timedelta(hours=24)
        ):
            raise ValidationError(
                {"timing": ["Orders cannot be cancelled after 24 hours"]}
            )

        # Delegate to aggregate method (which has its own Layer 3 invariants)
        order.cancel(command.reason)
        repo.add(order)


@domain.aggregate
class Account:
    balance: Float(default=0.0)
    is_frozen: Boolean(default=False)


@domain.aggregate
class CreditPolicy:
    max_single_transfer: Float(required=True)


@domain.domain_service(part_of=[Account, CreditPolicy])
class TransferValidationService:
    """Cross-aggregate validation that checks multiple aggregates."""

    @classmethod
    def validate_transfer(cls, source: Account, policy: CreditPolicy, amount: float):
        # Layer 4: Cross-aggregate business rule
        if amount > policy.max_single_transfer:
            raise ValidationError(
                {
                    "amount": [
                        f"Transfer exceeds policy limit of {policy.max_single_transfer}"
                    ]
                }
            )

        # Layer 4: External state check
        if source.is_frozen:
            raise ValidationError({"account": ["Source account is frozen"]})


# --8<-- [end:guards]

# --8<-- [start:command]
from protean.fields import List


@domain.command(part_of=Order)
class PlaceOrder:
    order_id: Identifier(identifier=True)
    customer_id: Identifier(required=True)
    items: List(required=True)
    total: Float(required=True, min_value=0.0)
    currency: String(required=True, max_length=3)


# --8<-- [end:command]


# --8<-- [start:in_action]
@domain.aggregate
class CustomerCredit:
    customer_id: Identifier(identifier=True)
    is_suspended: Boolean(default=False)


def submit_order():
    # --- Layer 1: Field Constraints ---
    # Triggered at command construction
    command = PlaceOrder(
        order_id="ord-123",
        customer_id="cust-456",
        items=[{"product_id": "prod-1", "quantity": 2, "unit_price": 29.99}],
        total=59.98,
        currency="USD",
    )
    # If customer_id is missing → ValidationError (required field)
    # If total is negative → ValidationError (min_value constraint)
    # If currency is longer than 3 characters → ValidationError (max_length)

    current_domain.process(command, asynchronous=False)


@domain.command_handler(part_of=Order)
class PlaceOrderHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def place_order(self, command: PlaceOrder):
        # --- Layer 4: Handler Guards ---
        # Check customer credit status (cross-aggregate)
        credit = current_domain.repository_for(CustomerCredit).get(command.customer_id)
        if credit.is_suspended:
            raise ValidationError({"credit": ["Customer credit is suspended"]})

        # --- Layer 2: Value Object Invariants ---
        # Triggered when constructing the Money value object
        total = Money(amount=command.total, currency=command.currency)
        # If currency is "XYZ" → ValidationError (invalid currency in Money VO)

        # --- Layer 3: Aggregate Invariants ---
        order = Order(
            order_id=command.order_id,
            customer_id=command.customer_id,
            items=[OrderItem(**item) for item in command.items],
            total=total,
        )
        order.place()
        # @invariant.post checks: must have items, total must match items
        # If no items → ValidationError
        # If total doesn't match → ValidationError

        current_domain.repository_for(Order).add(order)


# --8<-- [end:in_action]
domain.init(traverse=False)
